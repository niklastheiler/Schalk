# Abnahmebericht Schalk (technische und fachliche Prüfung)

Stand: 22.11.2026 · geprüfte Basis: `main` @ 7430dc3 (Version 1.3.2) · Prüfbranch: `claude/kind-brown-bosr4c`

Dieser Bericht dokumentiert die unabhängige Prüfung vor dem ersten produktiven Einsatz. Er unterscheidet durchgehend zwischen
**technisch nachgewiesen** (Test, Messung oder Validator), **organisatorisch zu klären** (Betreiber, Steuerberater) und
**rechtlich zu beurteilen**. Eine pauschale „GoBD-Konformität“ wird ausdrücklich **nicht** bescheinigt: Die GoBD verlangen
neben der Software ein ordnungsgemäßes Verfahren beim Anwender (Verfahrensdokumentation, internes Kontrollsystem,
Datensicherung). Eine Softwareprüfung kann nur den technischen Teil nachweisen.

---

## A. Executive Summary

**Gesamtzustand.** Schalk ist eine Desktop-Anwendung für Windows 11 (PySide6, Python 3.15, rund 10 000 Zeilen) für
Einzelunternehmer: Ausgangsrechnungen als ZUGFeRD/XRechnung, Angebote, Mahnungen, Kassenbuch, Eingangsrechnungen.
Die Daten liegen in einer SQLite-Datenbank, die nur im Arbeitsspeicher entschlüsselt vorliegt und auf der Platte mit
Fernet (AES-128-CBC + HMAC-SHA256) verschlüsselt ist; der Schlüssel ist per Windows-DPAPI an das Benutzerkonto gebunden.
Es gibt keinen Server, keine Web-Oberfläche und keine Mehrbenutzer- oder Mandantenverwaltung.

Die Ausgangsbasis war bereits solide: Beträge werden mit `Decimal` gerechnet, festgeschriebene Rechnungen und
Kassenbuchungen sind über SHA-256-Hash-Ketten gesichert, Rechnungen werden erst beim Festschreiben lückenlos
nummeriert, Stornos laufen über Stornorechnungen bzw. Gegenbuchungen, und jede E-Rechnung wird vor dem Festschreiben
gegen das offizielle EN-16931-Schematron geprüft.

**Wichtigste Erkenntnisse (vor der Prüfung)**
1. *Hoch, Buchhaltungslogik:* „Teilbezahlt“ war nur ein Status ohne Betrag. Mahnungen forderten deshalb auch nach einer
   Teilzahlung den vollen Rechnungsbetrag, und die Auswertung zählte Zahlungen nach Rechnungsdatum statt nach Zahlungseingang.
2. *Hoch, Datenintegrität:* Festschreibungen wurden nur asynchron gespeichert. Bei einem Absturz direkt danach konnte eine
   Rechnungsnummer, deren PDF bereits archiviert war, ein zweites Mal vergeben werden.
3. *Hoch, GoBD:* Der Verlauf (Audit-Log) war nicht gegen Veränderung gesichert, Stammdatenänderungen (Firmendaten, Kunden)
   wurden nicht protokolliert, und es gab keinen maschinell auswertbaren Datenexport für die Betriebsprüfung (Z3).
4. *Mittel, E-Rechnung:* Eingehende E-Rechnungen wurden gelesen, aber nicht gegen die Regeln geprüft. Profile, die keine
   E-Rechnung im Sinne des § 14 UStG sind (MINIMUM, BASIC WL), wurden nicht erkannt.
5. *Mittel, Sicherheit:* Die Download-Adresse des Auto-Updates wurde nicht geprüft. Die Setup-EXE ist nicht code-signiert.

**Durchgeführte Verbesserungen.** Zahlungsverwaltung, sofortiges Speichern beim Festschreiben, Hash-Kette über den Verlauf,
Protokollierung aller Stammdatenänderungen, Lückenprüfung der Nummernkreise, GoBD-Datenexport (CSV + `index.xml` nach dem
Beschreibungsstandard), Archivierung versandter Mahnungen, Regelprüfung eingehender E-Rechnungen, Härtung von XML-Import,
Wiederherstellung und Update. Dazu kommen 33 neue Regressionstests und ein neuer CI-Qualitätsjob (Lint, bandit, pip-audit).
Einzelheiten stehen in den Abschnitten F und H.

**Verbleibende Risiken.** Siehe K: fehlende Code-Signatur, Hash-Ketten ohne externe Verankerung (das Löschen des jeweils
letzten Datensatzes bleibt unbemerkt), offene fachliche Lücken (Skonto, Anzahlungs- und Schlussrechnungen, Gutschriftsverfahren,
UBL-Regelprüfung).

**Einschätzung:** **CONDITIONAL GO** (Begründung in K).

---

## B. Architekturbericht

### Bestehende Architektur

| Schicht | Komponenten | Bewertung |
|---|---|---|
| Start/Infrastruktur | `run.py`, `src/main.py` (Einzelinstanz-Lock, Logging, Absturzprotokoll) | gut |
| Persistenz | `src/models/database.py`: SQLAlchemy-Modelle; SQLite nur im RAM, verschlüsselte Datei, atomarer Hintergrund-Schreiber | gut; durchdacht (kein Klartext auf der Platte) |
| Geschäftslogik | `src/controllers/db_controller.py` (≈1 400 Zeilen): Nummernkreise, Festschreiben, Storno, Kassenbuch, Hash-Ketten, Integritätsprüfung, Cache | fachlich korrekt aufgebaut, aber groß (siehe technische Schulden) |
| Fachmodule | `utils/calculations.py`, `tax.py`, `zugferd_generator.py`, `einvoice_*`, `pdf_generator.py`, `pdfa.py`, `archive.py`, `backup.py`, `updater.py`, neu `gobd_export.py` | klare Zuständigkeiten, gut testbar |
| Oberfläche | `src/views/*` (qfluentwidgets), Signal-Bus für Aktualisierungen | sauber getrennt; die Views rufen nur den Controller auf |

**Datenfluss beim Festschreiben:** Editor → `DBController._finalize` → Pflichtangaben (§ 14 Abs. 4 UStG) → Nummer → EN-16931-
Schematron (Saxon) → Hash-Kette → Commit → **jetzt synchron** auf die Platte → ZUGFeRD-PDF/A-3 rendern → schreibgeschützt
archivieren (SHA-256 in der DB).

### Identifizierte Schwachstellen und Änderungen

| Schwachstelle | Änderung |
|---|---|
| Festschreiben nur asynchron persistiert | `_commit(durable=True)` bzw. automatisch bei Festschreibungen: wartet, bis die verschlüsselte Datei geschrieben ist |
| Zahlungen nicht modelliert | neue Tabelle `payments` (unveränderlich, Rückbuchung als negativer Betrag), `invoices.paid_amount`, Status folgt den Zahlungen |
| Audit-Log ungeschützt | `document_history.hash_chain`, Versiegelung beim Commit in Einfügereihenfolge, einmalige Migration bestehender Einträge |
| fehlende Indizes für die Kette | Index `ix_invoices_finalized (finalized_at, id)`; bestehende Datenbanken erhalten neue Indizes automatisch |
| Schema-Migration nur für Spalten | `_add_missing_columns` legt jetzt auch fehlende Indizes an |

Gute Entscheidungen wurden beibehalten: In-Memory-SQLite mit verschlüsselter Datei, DPAPI-Schlüssel, Caches im Controller,
Schematron-Prüfung vor dem Festschreiben.

### Verbleibende technische Schulden

- `DBController` vereint Rechnungen, Angebote, Kassenbuch, Eingangsrechnungen, Zahlungen und Integrität in einer Klasse.
  Eine Aufteilung in Services (z. B. `InvoiceService`, `CashbookService`, `IntegrityService`) wäre sinnvoll. Sie wurde
  bewusst nicht vorgenommen, weil sie das Risiko neuer Fehler kurz vor der Abnahme erhöht und funktional nichts verbessert.
- Geldbeträge liegen als SQLite-`REAL` (Float) in der Datenbank. Gerechnet wird durchgehend mit `Decimal`, gespeichert
  werden auf Cent gerundete Werte. Das ist bis weit über 10¹² € exakt darstellbar und unkritisch. Für eine künftige
  Hauptversion empfiehlt sich trotzdem die Speicherung in ganzen Cent (`INTEGER`).
- Es gibt keine CHECK-Constraints in der Datenbank. Die Regeln werden im Controller durchgesetzt; direkte Datenbankzugriffe
  sind nur mit dem DPAPI-Schlüssel des Benutzers möglich.

---

## C. GoBD-Prüfbericht

Grundlage: GoBD in der Fassung des BMF-Schreibens vom 14.07.2025 (zweite Änderung, Aufbewahrung von E-Rechnungen),
§§ 145–147 AO, § 14b UStG, § 257 HGB.

| Anforderung | Status | Technischer Nachweis | Festgestellte Mängel / Hinweise |
|---|---|---|---|
| Nachvollziehbarkeit (Rz. 30 ff.): Beleg → Buchung | Bestanden | Rechnung ↔ archiviertes PDF (SHA-256), Kassenbuchung ↔ Beleg (SHA-256), Eingangsrechnung ↔ Originaldatei (SHA-256); Tests `test_invoices`, `test_cashbook_and_storage` | – |
| Protokollierung von Änderungen (Rz. 58 ff., 107 ff.) | Bestanden (neu) | Verlauf für Rechnungen, Angebote, Kassenbuch, Eingangsrechnungen, **neu** auch Kunden, Firmendaten/Einstellungen, Zahlungen, Mahnungen, Exporte; Windows-Benutzer und Zeitstempel | vorher keine Protokollierung von Stammdaten |
| Unveränderbarkeit festgeschriebener Daten (Rz. 58 ff.) | Teilweise bestanden | Festgeschriebene Rechnungen/Buchungen sind über die API nicht änderbar (`GoBDError`), Korrektur nur per Storno; Hash-Ketten über Rechnungen, Kassenbuch und **neu** den Verlauf; Tests `test_history_is_hash_chained`, `test_deleted_history_entry_is_detected` | Die Ketten haben keinen geheimen Schlüssel und keine externe Verankerung. Wer das Windows-Konto kontrolliert, kann die Datenbank entschlüsseln und Ketten neu berechnen. Das Löschen des jeweils **letzten** Datensatzes bleibt unbemerkt. Empfehlung in K. |
| Vollständigkeit, lückenlose Nummernkreise (Rz. 36 ff.) | Bestanden (neu) | Nummern erst beim Festschreiben; **neu** Lückenprüfung je Jahr für Rechnungs- und Kassenbelegnummern (`test_missing_invoice_number_is_detected`) | Angebotsnummern dürfen Lücken haben (Angebote sind löschbar, nicht buchungsrelevant). |
| Zeitgerechte Erfassung (Rz. 46 ff.), Kassenbuch täglich (§ 146 Abs. 1 S. 2 AO) | Organisatorisch zu klären | Kassenbuchungen werden mit Datum erfasst; Festschreiben per Knopf | Entwürfe bleiben bis zum Festschreiben änderbar. Der Anwender muss zeitnah festschreiben (Empfehlung: täglich, spätestens zum Monatsende). |
| Ordnung, Kassenbestand nie negativ | Bestanden | `_check_cash_balance` prüft jeden Tag, auch bei Rückdatierung (`test_cashbook_rules`) | – |
| Storno/Korrektur (Rz. 64) | Bestanden | Stornorechnung (Typ 381) mit Bezug auf die Originalrechnung; Kassen-Gegenbuchung; Eingangsrechnungen werden nur storniert, nie gelöscht | Eine Berichtigung (Rn. 51b BMF 15.10.2025) erfolgt per Storno und neuer Rechnung; eine eigene „berichtigte Rechnung“ gibt es nicht. |
| Aufbewahrung (Rz. 113 ff.; § 14b UStG, § 147 AO) | Bestanden (technisch) | Archivdateien schreibgeschützt mit Hash; ZUGFeRD-PDF enthält den strukturierten Teil; erhaltene E-Rechnungen werden als Originaldatei unverändert gespeichert; **neu** auch versandte Mahnungen | Aufbewahrungsfristen (8 bzw. 10 Jahre) erzwingt die Software nicht durch Löschsperren. Es gibt keine Löschfunktion für festgeschriebene Daten, das genügt. |
| Lesbarkeit / Formate | Bestanden | PDF/A-3 (veraPDF über Mustang: gültig), XML nach EN 16931 | – |
| Datensicherung | Teilweise bestanden | Backup als eine Datei (CRC-geprüft), monatliche Erinnerung, automatische Sicherung vor Updates; **neu** `PRAGMA integrity_check` beim Einspielen | Backups sind unverschlüsselt (bewusste Entscheidung seit 1.3.1); Lagerung und Rhythmus sind organisatorisch festzulegen. |
| Datenzugriff Z1/Z2 | Organisatorisch zu klären | Lesender Zugriff über die Oberfläche (Listen, Filter, Verlauf) | Z1/Z2 erfordern einen Prüfer-Arbeitsplatz am Gerät des Unternehmers; es gibt keine eigene Prüferrolle (Einzelbenutzer). |
| Datenträgerüberlassung Z3 (Rz. 165 ff.) | Bestanden (neu) | **neu** GoBD-Datenexport: 7 Tabellen als CSV + `index.xml` (GDPdU-Beschreibungsstandard) + Belege; `tests/test_gobd_export.py` prüft Struktur und Reihenfolge der Elemente | Die Datei wurde nicht mit IDEA selbst eingelesen (nicht verfügbar). Die DTD `gdpdu-01-08-2002.dtd` liegt nicht bei. |
| Internes Kontrollsystem, Berechtigungen, Funktionstrennung | Organisatorisch zu klären | Einzelbenutzer-Anwendung, Authentisierung über das Windows-Konto | Kein Rollenkonzept und kein Vier-Augen-Prinzip; bei einem Einzelunternehmer meist nicht erforderlich. |
| Verfahrensdokumentation (Rz. 151 ff.) | Teilweise bestanden | **neu** `docs/VERFAHRENSDOKUMENTATION.md` (technischer Teil) | Allgemeine Beschreibung, Betriebs- und IKS-Teil muss der Anwender ergänzen. |

---

## D. ZUGFeRD- und E-Rechnungs-Prüfbericht

| Punkt | Ergebnis |
|---|---|
| Ausgangsformate | ZUGFeRD 2 / Factur-X, Profil **EN 16931** (PDF/A-3b mit eingebetteter `factur-x.xml`, AFRelationship `Data`); **XRechnung 3.0** (CII) als Export |
| Profile BASIC / EXTENDED | nicht erzeugt. EN 16931 deckt alle unterstützten Geschäftsfälle ab; BASIC wäre eine Teilmenge, EXTENDED ist nicht nötig. |
| Syntax/XSD | `drafthorse` serialisiert gegen das Factur-X-EN16931-XSD; das Ergebnis jeder Prüfung wird angezeigt |
| EN-16931-Geschäftsregeln | vor jedem Festschreiben offizielles Schematron (Factur-X EN16931, Saxon-HE); beim XRechnung-Export CEN 1.3.16 + KoSIT XRechnung 3.0.2 |
| Unabhängige Validierung | **Mustang 2.26.0** (inkl. veraPDF für PDF/A-3) in der CI für 12 Steuerfälle × 2 Formate; lokal nachgeprüft am 22.11.2026: **24 von 24 gültig** |
| PDF ↔ XML | `tests/test_calculation_crosscheck.py`: 60 zufällige Rechnungen (fester Seed), Summen aus XML = DB = unabhängige Referenzrechnung; das PDF wird aus denselben Daten erzeugt |
| Steuerfälle | 19 %/7 % gemischt, Rabatt + Nachlass, § 19 UStG, § 4 UStG steuerfrei, § 13b Reverse Charge (AE), innergemeinschaftliche Lieferung (K), Ausfuhr (G), Leistungszeitraum, Behörde (Leitweg-ID), Storno, Sonderzeichen |
| Rundung | Positionsbetrag kaufmännisch auf Cent; USt je Steuersatz auf die gerundete Bemessungsgrundlage (BR-CO-17); Nachlass anteilig je Steuersatz verteilt, Rest beim letzten Satz |
| Eingang | CII (XRechnung, ZUGFeRD-PDF) und UBL (Invoice, CreditNote) werden gelesen; Original unverändert archiviert; Dubletten-Erkennung (Datei-Hash bzw. Lieferant + Nummer) |
| **Neu** Eingangsprüfung | CII gegen CEN-EN-16931-Schematron (XRechnung zusätzlich KoSIT); MINIMUM / BASIC WL als „keine E-Rechnung“ erkannt (BMF 15.10.2025); Ergebnis im Dialog und im Verlauf |
| XML-Sicherheit | kein Auflösen von Entitäten, kein Netzwerk, kein DTD-Laden; **neu** Dokumente mit DOCTYPE werden abgelehnt (XXE, Entity-Expansion); **neu** Größenlimit 50 MB |

**Gefundene und behobene Fehler:** fehlende Regelprüfung eingehender Rechnungen (E-1); Beträge teils mit einer
Nachkommastelle (`19.0`; formal zulässig, aber von Empfangssystemen nicht immer akzeptiert) → jetzt immer `19.00` (E-2).

**Verbleibende Einschränkungen**
- Für UBL-Eingangsrechnungen gibt es keine Schematron-Prüfung, weil das Regelwerk nicht mitgeliefert wird (Hinweis im Dialog).
- Je Rechnung ist nur ein Befreiungsgrund möglich; verschiedene 0-%-Kategorien (z. B. E und AE) in einer Rechnung gehen nicht.
- Skonto, Anzahlungs-, Teil- und Schlussrechnungen mit Anrechnung sowie das Gutschriftsverfahren (§ 14 Abs. 2 S. 2 UStG) werden nicht unterstützt.
- Die Währung ist nur EUR. Eingangsrechnungen in Fremdwährung werden erkannt, der Betrag muss in Euro eingetragen werden.
- Die umsatzsteuerliche Richtigkeit des Einzelfalls (z. B. ob § 13b tatsächlich greift) prüft keine Software. Sie ist **rechtlich zu beurteilen**.

---

## E. Security-Audit

Prüfrahmen: OWASP ASVS (soweit auf eine Desktop-Anwendung übertragbar), CWE, bandit 1.9.4, pip-audit 2.10.1.
Web-spezifische Punkte (CSRF, CORS, CSP, Session-Management, HTTP-Header, IDOR, Request Smuggling) sind **nicht
anwendbar**: Es gibt weder Server noch API noch Mehrbenutzerbetrieb. SQL läuft über SQLAlchemy mit Parametern; das einzige
dynamische SQL (`ALTER TABLE` der Schema-Migration) verwendet nur Namen aus den Modellen, keine Eingaben.

| # | Schwere | Komponente | Ursache → Auswirkung | Behebung | Regressionstest | Restrisiko |
|---|---|---|---|---|---|---|
| S-1 | Mittel | `utils/updater.py` | Download-URL kam ungeprüft aus der API-Antwort (beliebiger Host, auch `file:`) → bei manipulierter Antwort Download von fremder Quelle (Hash stammt aus derselben Antwort) | Nur `https://github.com/niklastheiler/Schalk/releases/download/…` wird angenommen und geöffnet | `test_setup_asset_is_found_with_digest` | an GitHub-Konto gebunden, siehe S-2 |
| S-2 | Mittel | Release/Updater | Setup nicht code-signiert; SHA-256 und Datei kommen aus derselben Quelle → Wer das GitHub-Konto übernimmt, kann ein Update verteilen | **offen**: Authenticode-Signatur im Release-Workflow und Prüfung der Signatur vor dem Start | – | mittel |
| S-3 | Niedrig | Updater | Das geprüfte Setup liegt im benutzerbeschreibbaren `%LOCALAPPDATA%` und wird mit Adminrechten gestartet (TOCTOU, CWE-367) | **offen**, wird mit S-2 gelöst (Signaturprüfung unmittelbar vor dem Start) | – | niedrig (setzt Schadcode im Benutzerkonto voraus) |
| S-4 | Niedrig | `einvoice_parser` | DOCTYPE mit internen Entitäten erlaubt | DOCTYPE wird abgelehnt, `load_dtd=False` | `test_document_type_declarations_are_refused`, `test_xml_external_entities_are_not_resolved` | – |
| S-5 | Niedrig | Eingangsrechnungen | keine Größenbegrenzung (Speicher-DoS) | 50 MB; große PDFs werden ohne strukturierte Daten erfasst | `test_oversized_files_are_not_read` | – |
| S-6 | Niedrig | `restore_database` | beschädigte oder fremde SQLite-Datei konnte die Datenbank ersetzen | `PRAGMA integrity_check` und Prüfung der Schalk-Tabellen | `test_restore_rejects_foreign_or_damaged_databases` | – |
| S-7 | Information | Backup | Backups sind unverschlüsselt (Entscheidung 1.3.1) | dokumentiert | – | organisatorisch: sicher lagern |
| S-8 | Information | Hash-Ketten | ohne Schlüssel bzw. externe Verankerung neu berechenbar | dokumentiert (C, K) | – | siehe K |
| S-9 | Information | Git-Historie | frühe Versionen (Juli 2026) enthielten fest eingetragene Standard-Passwörter für die damalige Verschlüsselung | heute ungenutzt (DPAPI), keine Wirkung | – | – |
| S-10 | Information | bandit B610/B310 | Fehlalarme (lokaler Callback `extra`, feste https-URLs) | mit Begründung annotiert | CI-Job `quality` | – |

**Abhängigkeiten:** pip-audit gegen alle gepinnten Pakete (`requirements*.txt`) am 22.11.2026: *No known vulnerabilities found*.
Lizenzen: MIT (Schalk), GPLv3 (PySide6-Fluent-Widgets, maßgeblich für die EXE), LGPLv3 (Qt), MPL 2.0 (Saxon-HE), Apache 2.0
(Prüfregeln). Das ist im README dokumentiert. Typosquatting: Alle Paketnamen wurden mit den offiziellen Projekten abgeglichen.
**Secrets:** keine aktiven Secrets im Repository oder in der Historie (Suche nach Schlüsseln, Tokens, `.pem`/`.pfx`/`.env`).
Der Release-Workflow nutzt nur `GITHUB_TOKEN`.

---

## F. Bug- und Qualitätsbericht

| # | Schwere | Fehler | Status | Test |
|---|---|---|---|---|
| F-1 | Hoch | Teilzahlungen ohne Betrag; Mahnung forderte trotz Teilzahlung den vollen Betrag | behoben: Zahlungen mit Betrag und Datum, Status ergibt sich daraus, Mahnung nennt Rechnungsbetrag, Zahlungen und offenen Betrag | `test_partial_and_full_payment_set_the_status`, `test_reminder_demands_only_the_outstanding_amount`, `test_payment_dialog_from_the_status_menu` |
| F-2 | Mittel | Auswertung „bezahlt“ nach Rechnungsdatum statt Zahlungseingang (falsch bei Ist-Versteuerung) | behoben: Zahlungseingänge nach Zahlungsdatum | über `payments_in_year` |
| F-3 | Hoch | Festschreibung nur asynchron gespeichert, Nummernvergabe bei Absturz doppelt möglich | behoben | `test_finalized_invoice_is_on_disk_immediately` |
| F-4 | Mittel | API erlaubte bei Anlage jeden Status (z. B. „Storniert“ ohne Stornorechnung) | behoben | `test_new_invoices_cannot_skip_the_process` |
| F-5 | Mittel | Rechnungsdatum in der Zukunft konnte festgeschrieben werden | behoben | `test_invoice_dated_in_the_future_is_not_finalized` |
| F-6 | Niedrig | Rechnung über 0 € (Nachlass = Rechnungsbetrag) ließ sich nicht als bezahlt markieren (beim Nachprüfen der eigenen Änderung gefunden) | behoben | `test_invoice_without_amount_due_can_be_marked_paid` |
| F-7 | Niedrig | Rückbuchung einer Zahlung nach Fälligkeit ließ die Rechnung „Offen“ statt „Überfällig“ | behoben | `test_returned_payment_reopens_and_becomes_overdue` |
| G-1 | Hoch | Verlauf manipulierbar ohne Erkennung | behoben (Hash-Kette) | `test_history_is_hash_chained`, `test_deleted_history_entry_is_detected`, `test_legacy_history_is_sealed_once` |
| G-2 | Mittel | Stammdatenänderungen nicht protokolliert | behoben | `test_master_data_changes_are_logged` |
| G-3 | Mittel | Nummernlücken wurden nicht erkannt | behoben | `test_missing_invoice_number_is_detected`, `test_number_gap_ranges` |
| G-4 | Hoch | kein Z3-Datenexport | behoben | `tests/test_gobd_export.py` (4 Tests) |
| G-5 | Mittel | versandte Mahnungen nicht archiviert | behoben (schreibgeschützt, SHA-256 im Verlauf) | `test_sent_reminder_is_archived` |
| G-6 | Mittel | Manipulation des bezahlten Betrags unentdeckt | behoben (Abgleich mit Zahlungen) | `test_manipulated_paid_amount_is_detected` |
| E-1 | Mittel | Eingangsrechnungen ohne Regelprüfung | behoben (CII) | `test_received_einvoice_is_checked_against_the_rules`, `test_minimum_profile_is_no_einvoice`, `test_check_of_received_invoice_is_logged` |
| E-2 | Niedrig | XML-Beträge `19.0` | behoben | über Mustang/Schematron |

**Migration bestehender Datenbanken (1.3.x):** wird mit `test_database_of_version_1_3_is_upgraded` geprüft. Neue Tabelle,
Spalten und Index werden angelegt, der bestehende Verlauf wird einmalig versiegelt. Rechnungen, die vor 1.4 als
„Bezahlt“ markiert wurden, haben keine Zahlung und lassen sich ohne Zahlung wieder öffnen. In der Auswertung erscheinen
sie nicht als Zahlungseingang.

**Nicht behoben (bewusst, mit Empfehlung):** siehe D (fachliche Lücken), K.

**Eigene Prüfung im zweiten Durchgang:** Dabei wurden F-6, eine verwaiste Archivdatei bei abgelehnter Mahnung (Archivierung jetzt nach
den Prüfungen), die Ablehnung großer Scan-PDFs (jetzt Erfassung ohne strukturierte Daten) und fehlende ZUGFeRD-2.0-Profilkennungen gefunden und behoben.

---

## G. Performance-Bericht

Messung mit `python tools/benchmark.py 1000` (temporärer Datenordner; Linux-Container, Python 3.13; absolute Werte unter
Windows abweichend, Verhältnisse vergleichbar):

| Messgröße | vorher | nachher | Bemerkung |
|---|---|---|---|
| 1 000 Rechnungen anlegen + festschreiben | 12,9 s | 16,5 s | |
| je Rechnung | 12,9 ms | 16,5 ms | +3,6 ms durch das synchrone Speichern beim Festschreiben (F-3) und das Versiegeln des Verlaufs |
| EN-16931-Prüfung (erste / weitere) | 0,32 s / 25 ms | 0,32 s / 32 ms | Messrauschen; Regeln werden beim Start im Hintergrund geladen |
| ZUGFeRD-PDF/A-3 erzeugen | 42 ms | 43 ms | |
| Datenbank verschlüsselt speichern | 12 ms | 16 ms | 1 000 Rechnungen ≈ 2 MB |
| GoBD-Integritätsprüfung (ohne Dateien) | 39 ms | 90 ms | zusätzlich Verlauf, Nummernlücken, Zahlungen |
| Start (Datenbank öffnen, Caches laden) | 0,22 s | 0,20 s | |

**Bewertung:** Es gibt keinen relevanten Engpass. Die Mehrkosten des Festschreibens sind gewollt, weil Datensicherheit vor
Geschwindigkeit geht, und bleiben bei einer Aktion pro Klick nicht spürbar. Das Profiling zeigt, dass beim Speichern die
Fernet-Verschlüsselung samt Base64 den größten Anteil hat (≈ 8 ms je 2 MB).

**Mögliche Optimierung, nicht umgesetzt:** Ein Dateiformat mit AES-GCM statt Fernet würde das Speichern etwa halbieren,
ist aber eine Formatänderung mit Migrationsrisiko. Erst ab mehreren 10 000 Rechnungen lohnenswert.

---

## H. Repository-Bericht

| Art | Inhalt |
|---|---|
| Neue Dateien | `src/utils/gobd_export.py`, `tools/benchmark.py`, `requirements-ci.txt`, `docs/AUDIT.md`, `docs/VERFAHRENSDOKUMENTATION.md`, `tests/test_audit_regressions.py`, `tests/test_calculation_crosscheck.py`, `tests/test_gobd_export.py` |
| Geänderte Module | `db_controller.py` (Zahlungen, Verlauf-Kette, Prüfungen), `database.py` (Payment, Spalten, Index, Restore-Prüfung), `einvoice_parser.py`, `einvoice_validation.py`, `zugferd_generator.py`, `pdf_generator.py` (Mahnung), `updater.py`, `paths.py`, Views (Zahlungsdialog, Eingangsprüfung, GoBD-Export, Auswertung, Mahnungen) |
| Entfernte Dateien/Abhängigkeiten | keine. Alle Abhängigkeiten werden genutzt, toter Code wurde nicht gefunden (pyflakes ohne Befund). |
| Konfiguration | `.github/workflows/einvoice-check.yml` (Job `quality`, Rechte, Timeouts) |
| Dokumentation | README (GoBD, Zahlungen, Export, Tests/CI), Abnahmebericht, Verfahrensdokumentation |

---

## I. CI/CD-Bericht

**Ursprünglicher Zustand:** `einvoice-check.yml` (Windows, Python 3.15): pytest, Beispielrechnungen, Mustang-Validierung
(Prüfsumme des Validators gepinnt). `release.yml` ruft diese Prüfung als Voraussetzung auf, baut die EXE mit Tests, führt einen
EXE-Selbsttest aus und testet den Installer. Wöchentlich läuft der Check auf neue Prüfregeln, Dependabot ist eingerichtet. Es
fehlten: Lint (pyflakes stand in den Dev-Abhängigkeiten, lief aber nirgends), statische Sicherheitsanalyse, Prüfung der
Abhängigkeiten auf Sicherheitslücken, eingeschränkte Token-Rechte und Timeouts.

**Verbesserungen**
- Neuer Job **`quality`** (Ubuntu, wenige Minuten): `pyflakes`, `bandit -ll` (ab mittlerem Schweregrad, bricht ab),
  `pip-audit` gegen alle gepinnten Abhängigkeiten. Die Werkzeuge stehen in `requirements-ci.txt` und werden von Dependabot aktualisiert.
- Da `release.yml` die Prüfung per `workflow_call` aufruft, ist der neue Job automatisch auch ein **Release-Gate**.
- `permissions: contents: read` als Standard, `timeout-minutes` für beide Jobs.
- Ein fehlgeschlagener Schritt bricht den Lauf zuverlässig ab: cmd mit Exitcode, pwsh mit `throw`, Mustang über den Bericht ausgewertet.

**Verbleibende Einschränkungen:** Actions sind auf Hauptversionen gepinnt, nicht auf Commit-SHAs; Dependabot aktualisiert
sie. Es gibt keine Coverage-Messung. Die Oberflächentests laufen offscreen und ersetzen keinen Klicktest unter Windows. Der
Release ist nicht reproduzierbar im Sinne bitgleicher Builds, weil PyInstaller Zeitstempel schreibt.

**Ausführungszeiten (erster Lauf auf diesem Stand, 22.11.2026, Run 45006632060):** `quality` 16 s (Ubuntu, Python 3.15.2),
`check` 3:40 min (Windows: Installation 46 s, Tests 49 s, Mustang-Validierung 1:44 min). Beide erfolgreich, die Jobs laufen parallel.

---

## J. Testbericht

| | vorher | nachher |
|---|---|---|
| Tests gesamt | 784 | 817 |
| erfolgreich | 784 | 817 |
| fehlgeschlagen / übersprungen | 0 / 0 | 0 / 0 |
| Laufzeit (lokal) | 30 s | 40 s |
| E-Rechnungen (Mustang, 12 Fälle × ZUGFeRD + XRechnung) | 24/24 gültig (CI) | 24/24 gültig (lokal nachgeprüft) |

Lokale Umgebung: Linux, Python 3.13, DPAPI durch eine Test-Attrappe ersetzt. Maßgeblich ist der CI-Lauf unter Windows
mit Python 3.15 und echter DPAPI: **erfolgreich** (alle Tests und 24/24 E-Rechnungen gültig, Run 45006632060).

**Neue Testschwerpunkte:** Zahlungen und Status, Manipulationserkennung (Verlauf, Nummern, Zahlungen), Haltbarkeit des
Festschreibens, Wiederherstellung, Migration 1.3 → 1.4, Eingangsprüfung, XML-Angriffe, GoBD-Export inklusive
`index.xml`-Struktur, eine **unabhängige Referenzrechnung** für 60 zufällige Rechnungen und Stornospiegelung.

**Nicht getestet:** echte Windows-Oberfläche per Hand, Update über einen echten GitHub-Release mit UAC, Import des
GoBD-Exports in IDEA, Absturz mitten im Schreiben unter Windows. Das atomare `os.replace` ist abgedeckt, ein Stromausfall nicht.

---

## K. Finale Abnahmeentscheidung

### **CONDITIONAL GO**

In den geprüften Bereichen sind keine kritischen und keine offenen hohen technischen Mängel bekannt. Alle gefundenen
hohen Mängel (F-1, F-3, G-1, G-4) sind behoben und durch Tests abgesichert. Ein uneingeschränktes GO wird nicht vergeben, weil:

1. **Vor dem Go-Live (Bedingungen)**
   - ~~Die CI (Windows, Python 3.15) muss auf diesem Stand grün sein, einschließlich des neuen `quality`-Jobs.~~ Erfüllt am 22.11.2026.
   - Der Anwender ergänzt die Verfahrensdokumentation (`docs/VERFAHRENSDOKUMENTATION.md`, Abschnitte „vom Anwender auszufüllen“)
     und stimmt sie mit seinem Steuerberater ab, ebenso die steuerliche Einordnung seiner Fälle (z. B. Kleinunternehmer, § 13b).
   - Er legt ein Datensicherungsverfahren fest: Backup mindestens monatlich und nach jedem Festschreiben des Kassenbuchs, verschlüsselt
     extern lagern. Dieses Backup ist zugleich die **externe Verankerung** der Hash-Ketten (siehe S-8).
2. **Unter kontrollierten Bedingungen nach dem Go-Live**
   - S-2/S-3: Code-Signatur des Setups einführen, bis dahin Updates nur aus dem offiziellen Release installieren.
   - Kassenbuch zeitnah festschreiben (organisatorisch).
   - Fachliche Lücken (Skonto, Anzahlungs- und Schlussrechnung, Gutschriftsverfahren, mehrere Befreiungsgründe, UBL-Prüfung):
     solche Fälle nicht mit Schalk abbilden, solange sie nicht umgesetzt sind.

Eine GoBD-Konformität im Rechtssinn kann diese Prüfung nicht bescheinigen. Technisch sind die prüfbaren Anforderungen
umgesetzt (Tabelle C). Organisatorische und rechtliche Punkte sind dort ausdrücklich als solche gekennzeichnet.
