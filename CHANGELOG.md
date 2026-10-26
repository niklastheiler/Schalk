# Changelog

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
