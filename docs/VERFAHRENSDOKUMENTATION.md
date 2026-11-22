# Verfahrensdokumentation Schalk – technischer Teil

Grundlage: GoBD (BMF-Schreiben vom 28.11.2019, geändert am 11.03.2024 und 14.07.2025), Rz. 151 ff.
Diese Unterlage beschreibt, **was die Software technisch tut**. Eine vollständige Verfahrensdokumentation braucht
zusätzlich die Angaben des Anwenders. Die betreffenden Stellen sind mit ✎ markiert und vom Anwender auszufüllen,
am besten zusammen mit dem Steuerberater. Bei jeder neuen Schalk-Version prüfen, ob sich etwas geändert hat
(siehe `CHANGELOG.md`).

## 1. Allgemeine Beschreibung

| | |
|---|---|
| Unternehmen ✎ | Name, Rechtsform (Einzelunternehmen), Steuernummer, Gewinnermittlung (EÜR/Bilanz), Soll- oder Ist-Versteuerung, Kleinunternehmer ja/nein |
| Eingesetzte Software | Schalk, Version laut Einstellungen → Sicherheit & GoBD → Über Schalk; Quellcode und Änderungshistorie: GitHub `niklastheiler/Schalk` |
| Einsatzbereich | Ausgangsrechnungen (ZUGFeRD/XRechnung), Angebote, Mahnungen, Zahlungseingänge zu Ausgangsrechnungen, Kassenbuch, Erfassung und Archivierung erhaltener Rechnungen |
| Nicht in Schalk ✎ | z. B. Finanzbuchhaltung/Buchungsjournal, Bankkonto, Lohn, Anlagenverzeichnis, Umsatzsteuer-Voranmeldung: Wer übernimmt das (Steuerberater/DATEV)? |
| Verantwortlich ✎ | Person, Vertretung |

## 2. Anwenderdokumentation (Arbeitsabläufe)

**Ausgangsrechnung**
1. Entwurf anlegen (Kunde, Positionen, Steuersatz je Position, bei 0 % ein Befreiungsgrund). Entwürfe sind änderbar und löschbar
   und haben noch keine Rechnungsnummer.
2. Status „Offen“ **schreibt fest**. Schalk prüft dabei die Pflichtangaben nach § 14 Abs. 4 UStG und die
   EN-16931-Regeln, vergibt die nächste lückenlose Nummer (`RE` + Jahr + Monat + laufende Nummer je Jahr), friert Verkäufer- und
   Empfängerdaten ein, nimmt die Rechnung in die Hash-Kette auf, speichert sofort und archiviert das ZUGFeRD-PDF/A-3 schreibgeschützt.
3. Danach ist die Rechnung unveränderbar. Korrektur nur über **Stornorechnung** (eigene Nummer, Typ 381, Bezug auf das
   Original) und, falls nötig, eine neue Rechnung.
4. **Zahlungen**: „Als bezahlt markieren“ erfasst die Zahlung des ganzen Rechnungsbetrags mit Datum (Teilzahlungen gibt es nicht). Eine Bareinnahme im Kassenbuch zu einer Rechnung wird beim Festschreiben des Kassenbuchs als Zahlung gebucht, ihr Storno bucht sie zurück. Der Status ergibt
   sich aus der Summe der Zahlungen. Eine Rücklastschrift wird als negative Zahlung gebucht, Zahlungen werden nie geändert oder gelöscht.
5. Das **PDF-Symbol** rechts neben dem Status druckt festgeschriebene Rechnungen, Angebote und die zuletzt erstellte Mahnung.
   Bei Entwürfen ist es ausgegraut.
6. **Mahnungen** (bis 3 Stufen, frühestens 14 Tage auseinander) nennen den offenen Betrag. Eine Kopie jeder gespeicherten Mahnung
   wird schreibgeschützt archiviert.

**Kassenbuch**: Buchungen werden als Entwurf erfasst (Datum, Betrag, Art, Text, PDF-Beleg). „Festschreiben“ vergibt die
Belegnummern (`K` + Jahr + laufende Nummer) und versiegelt die Buchungen. Korrektur danach nur per Storno-Gegenbuchung.
Der Bestand darf an keinem Tag negativ werden. ✎ Festschreib-Rhythmus festlegen (Empfehlung: täglich, § 146 Abs. 1 S. 2 AO).

**Erhaltene Rechnungen**: Hochladen als PDF, ZUGFeRD-PDF oder XRechnung (CII/UBL). Strukturierte Daten werden übernommen,
CII-Rechnungen gegen EN 16931 geprüft. Das Prüfergebnis steht im Verlauf, die Originaldatei wird unverändert und
schreibgeschützt mit SHA-256 archiviert. Dubletten werden gemeldet. Erhaltene Rechnungen werden nie gelöscht, nur storniert.
✎ Wer prüft erhaltene Rechnungen sachlich (Leistung erhalten, Betrag richtig) und wann?

## 3. Technische Systemdokumentation

| Komponente | Beschreibung |
|---|---|
| Plattform | Windows 11 ab 24H2, 64 Bit; Installation nach `C:\Programme\Schalk` (Inno Setup) |
| Datenhaltung | SQLite-Datenbank, nur im Arbeitsspeicher entschlüsselt; Datei `%LOCALAPPDATA%\Schalk\schalk.enc.db`, Fernet (AES-128-CBC + HMAC-SHA256), atomar geschrieben (temporäre Datei + `os.replace`) |
| Schlüssel | zufällig erzeugt, per Windows-DPAPI an das Benutzerkonto gebunden (`schalk.key`) |
| Archiv | `%LOCALAPPDATA%\Schalk\app_data\archive\invoices` (Rechnungen), `…\archive\reminders` (Mahnungen), `…\app_data\incoming_invoices` (erhaltene Rechnungen), `…\assets\receipts` (Kassenbelege); Dateien schreibgeschützt, SHA-256 in der Datenbank |
| Tabellen | `invoices`, `invoice_items`, `payments`, `quotes`, `quote_items`, `cashbook_entries`, `incoming_invoices`, `customers`, `settings`, `document_history` |
| Hash-Ketten | SHA-256 über (Datensatzinhalt + Vorgänger-Hash) für festgeschriebene Rechnungen inklusive Positionen, Verkäufer- und Empfängerdaten, für Kassenbuchungen und für **jeden** Verlaufseintrag |
| Integritätsprüfung | beim Start im Hintergrund (ohne Dateien), vollständig unter Einstellungen → Sicherheit & GoBD: alle Ketten, lückenlose Nummern je Jahr, Zahlungen gegen den bezahlten Betrag, Hash aller archivierten Dateien |
| E-Rechnung | ZUGFeRD 2 / Factur-X Profil EN 16931 (PDF/A-3b, `factur-x.xml`, AFRelationship Data); XRechnung 3.0 CII; Prüfung mit dem offiziellen Schematron (Saxon-HE), Versionen in `src/resources/rules.json` |
| Protokoll | `%LOCALAPPDATA%\Schalk\schalk.log` (technisch, rotierend); fachlicher Verlauf in `document_history` |

## 4. Betriebsdokumentation

| Thema | Technik | ✎ Organisation |
|---|---|---|
| Datensicherung | Backup als eine `.backup`-Datei (Datenbank + alle archivierten Dokumente, CRC-geprüft); Erinnerung nach einem Monat; automatische Sicherung der verschlüsselten Datenbank vor jedem Update (`backups`, letzte 5) | Rhythmus, Speicherort (extern, verschlüsselt, z. B. verschlüsseltes Laufwerk), Aufbewahrung, regelmäßiger Test einer Wiederherstellung |
| Wiederherstellung | Einstellungen → Sicherheit & GoBD → Backup einspielen; prüft die Datei (CRC, SQLite-Integrität, Schalk-Tabellen) vor dem Ersetzen; die bisherige Datenbank bleibt als `.bak` erhalten | Wer, wann, Protokoll |
| Updates | Prüfung beim Start gegen GitHub-Releases, Download nur von `github.com/niklastheiler/Schalk/releases/download`, SHA-256-Prüfung, Sicherung vor der Installation | Updates zeitnah installieren; Changelog lesen |
| Zugriffsschutz | Windows-Anmeldung; Datenbankschlüssel nur für dieses Windows-Konto lesbar | Passwort/Windows Hello, Bildschirmsperre, Festplattenverschlüsselung (BitLocker) |
| Integrität | Prüfung beim Start; Meldung bei Abweichungen | Bei einer Meldung nichts weiter erfassen, Backup prüfen, Steuerberater informieren |

## 5. Datenverarbeitung, Schnittstellen und Export

| Schnittstelle | Richtung | Inhalt |
|---|---|---|
| ZUGFeRD-PDF / XRechnung | Ausgang | Rechnung an Kunden bzw. Behörden (Leitweg-ID als Käuferreferenz) |
| E-Rechnungs-Import | Eingang | XRechnung/ZUGFeRD/UBL; PDF ohne strukturierte Daten |
| „DATEV Export“ | Ausgang | ZIP mit den bezahlten Rechnungen eines Monats für Steuerberater/DATEV Unternehmen online (keine Buchungssätze). Stornierte Rechnungen und ihre Stornorechnungen sind nicht enthalten. |
| **GoBD-Datenexport** | Ausgang | Einstellungen → Sicherheit & GoBD: Rechnungen, Positionen, Zahlungen, Kassenbuch, erhaltene Rechnungen, Kunden, Verlauf als CSV (UTF-8, `;`, Dezimalkomma) mit `index.xml` nach dem Beschreibungsstandard (GDPdU), optional mit allen Belegen. Gedacht für die Datenträgerüberlassung (Z3). Jeder Export wird im Verlauf protokolliert. |

Datenzugriff Z1/Z2 ✎: Der Prüfer erhält am Arbeitsplatz Lesezugriff über die Oberfläche. Schalk hat keine eigene Prüferrolle,
der Zugang wird beaufsichtigt.

## 6. Berechtigungskonzept und internes Kontrollsystem

- Schalk ist eine Einzelplatz- und Einzelbenutzer-Anwendung. Jede Aktion wird mit dem Windows-Benutzernamen und einem Zeitstempel (UTC)
  im Verlauf protokolliert.
- Technische Kontrollen: Pflichtangaben und EN-16931-Prüfung vor dem Festschreiben, Kassenbestand nie negativ, Zahlungen nicht
  höher als der offene Betrag, Statusübergänge nur in der vorgesehenen Reihenfolge, Rechnungsdatum nicht in der Zukunft,
  Integritätsprüfung.
- ✎ Organisatorische Kontrollen: Abgleich Kassenbestand mit Zählung, Abgleich der Zahlungseingänge mit dem Kontoauszug,
  Durchsicht der offenen Posten, Vertretungsregel.

## 7. Grenzen der technischen Unveränderbarkeit

Die Hash-Ketten erkennen nachträgliche Änderungen, eingefügte und (bis auf den jeweils letzten) gelöschte Datensätze.
Sie verwenden keinen geheimen Schlüssel: Wer das Windows-Konto kontrolliert, könnte die Datenbank mit eigenem Programmcode
entschlüsseln und die Ketten neu berechnen. Deshalb gehört zum Verfahren eine **externe Sicherung** (regelmäßiges Backup bzw.
der GoBD-Datenexport, aufbewahrt außerhalb des Rechners, z. B. beim Steuerberater). Gegen diese Sicherung lässt sich jede
spätere Veränderung nachweisen.

## 8. Änderungsprozess der Software

Änderungen laufen über Pull Requests auf GitHub. Jeder Pull Request und jedes Release durchläuft automatisch
Lint, statische Sicherheitsanalyse, Prüfung der Abhängigkeiten auf bekannte Sicherheitslücken, alle Tests und die
unabhängige Validierung der E-Rechnungen aller Steuerfälle (Mustang inklusive veraPDF). Ein Release wird nur
veröffentlicht, wenn alles besteht, die EXE den Selbsttest besteht und sich das Setup installieren und deinstallieren lässt.
Die Änderungen jeder Version stehen in `CHANGELOG.md`, der Prüfbericht in `docs/AUDIT.md`.
