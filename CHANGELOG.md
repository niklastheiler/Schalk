# Changelog

## 1.1

Schwerpunkt: nachweisbar gültige E-Rechnungen.

**Installation/Update:** `Schalk-v1.1-windows-x64.zip` herunterladen, entpacken und den bisherigen Programmordner ersetzen. Die Daten liegen in `%LOCALAPPDATA%\Schalk` und bleiben erhalten.

### Neu
- **Offizielles XRechnung-Prüfregelwerk:** Vor jedem XRechnung-Export laufen dieselben Regeln wie im KoSIT-Validator der Behörden-Eingangsportale (CEN EN 16931 1.3.16 und XRechnung 3.0.2). Eine XRechnung, die abgelehnt würde, wird nicht mehr ausgegeben.
- **Beispielrechnungen** für alle Steuerfälle unter `samples/e-rechnungen` zum Prüfen mit externen Validatoren (KoSIT, Mustang, veraPDF).
- **Automatische Prüfung bei jeder Änderung:** Alle Steuerfälle werden mit dem unabhängigen Mustang-Validator geprüft, einschließlich PDF/A-3 per veraPDF. Grenzfälle sind ebenfalls abgedeckt: Sonderzeichen und lange Texte, 40 Positionen mit gemischten Steuersätzen, seltene Einheiten, Bruchmengen und Rundung.
- **Release nur nach bestandener Prüfung:** Eine neue Version wird erst gebaut und veröffentlicht, wenn alle Tests und die Mustang-Prüfung bestehen.
- **Abhängigkeiten aktuell halten:** Dependabot schlägt wöchentlich gebündelte Updates der Python-Pakete und GitHub-Actions vor; jedes Update durchläuft die E-Rechnungs-Prüfung.
- **Patch-Releases:** `tools/bump_version.py` setzt Version und Changelog-Abschnitt in einem Schritt, z. B. für ein schnelles Sicherheitsupdate.
- **Prüfregeln aktuell halten:** Ein wöchentlicher Check meldet neue Versionen der offiziellen Prüfregeln und des Mustang-Validators als Issue. `tools/rule_updates.py --update` aktualisiert sie.

### Behoben
- Innergemeinschaftliche Lieferungen ließen sich nicht festschreiben, weil das Lieferland fehlte (BR-IC-12).
- XRechnung mit Positionsrabatt: Der Abschlag fehlte beim Bruttopreis (PEPPOL-EN16931-R046).
- XRechnung: unzulässige Währungsangabe an Netto- und Bruttosumme (CII-DT-031).
- Stornorechnung als XRechnung ohne Zahlungsangaben (BR-DE-1).
- Einheiten wie Kilogramm, Meter oder Pauschale wurden in der E-Rechnung als „Stück“ kodiert, jetzt mit korrektem UN/ECE-Code.
- Zeilenumbrüche in Positionsbeschreibungen gingen in der PDF verloren.
- Absturz beim Beenden der Tests unter Windows; Timer, die schon gelöschte Fenster noch aufriefen, sind jetzt an ihr Fenster gebunden.

### Geändert
- Der GiroCode (QR-Code) wird nicht mehr auf die Rechnung gedruckt.

## 1.0

Erste finale Version von Schalk, dem Rechnungs- und Buchhaltungsprogramm für kleine Unternehmen unter Windows 10/11.

**Installation:** `Schalk-v1.0-windows-x64.zip` herunterladen, entpacken und `Schalk\Schalk.exe` starten. Eine Python-Installation ist nicht nötig.

### Funktionen
- **Rechnungen** als E-Rechnung nach EN 16931:
  - ZUGFeRD/Factur-X als PDF/A-3 mit GiroCode, zusätzlicher Export als XRechnung 3.0
  - Prüfung der Pflichtangaben nach § 14 UStG und der EN-16931-Regeln vor dem Festschreiben
  - Status-Dropdown, das nur die jeweils sinnvollen Folgestatus anbietet
  - Mahnwesen und Stornorechnungen
- **Angebote** mit Umwandlung in eine Rechnung per Klick auf die Rakete.
- **Steuern** pro Position (19 %, 7 %, 0 % mit Befreiungsgrund), Kleinunternehmerregelung nach § 19 UStG.
- **Kassenbuch**:
  - Einträge erst als änderbare Entwürfe erfassen, dann festschreiben
  - Storno per Gegenbuchung
  - Belege nur als PDF
- **Eingangsrechnungen**: Einlesen von XRechnung (CII/UBL) und ZUGFeRD, Archivierung der Originaldatei.
- **Kunden**, **Auswertung** sowie **DATEV-Export** für Rechnungen, Kassenbuch und Eingangsrechnungen.

### Sicherheit und GoBD
- Verschlüsselte Datenbank, Schlüssel per Windows-DPAPI an das Benutzerkonto gebunden (kein Passwort beim Start).
- Lückenlose Rechnungsnummern erst beim Festschreiben. Danach sind Rechnungen unveränderbar.
- Hash-Ketten für Rechnungen und Kassenbuch, schreibgeschützte Archivdateien, Integritätsprüfung beim Start.
- Verlaufsprotokoll jeder Aktion mit Windows-Benutzer.
- Backup als einzelne, mit eigenem Passwort verschlüsselte `.backup`-Datei inklusive aller archivierten Dokumente.
