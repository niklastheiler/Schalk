# Schalk

Rechnungs- und Buchhaltungsprogramm für kleine Unternehmen unter **Windows 10/11**: Kundenrechnungen als E-Rechnung (ZUGFeRD/XRechnung), Angebote, Mahnungen, Kassenbuch, Eingangsrechnungen, Kunden und Auswertung. Die Datenhaltung ist GoBD-orientiert.

## Installation (aus dem Quellcode)

Voraussetzung: Python 3.11, 3.12 oder 3.13 (64 Bit) von python.org.

```powershell
git clone https://github.com/niklastheiler/Schalk.git
cd Schalk
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py
```

## Programm als EXE bauen

```powershell
build.bat
```

Das Skript legt eine virtuelle Umgebung an, führt die Tests aus und erzeugt `dist\Schalk\Schalk.exe`. Diesen Ordner kann man auf andere Rechner kopieren.

## Datenablage und Sicherheit

| Was | Wo |
|---|---|
| Datenbank (verschlüsselt) | `%LOCALAPPDATA%\Schalk\schalk.enc.db` |
| Schlüssel (Windows-DPAPI) | `%LOCALAPPDATA%\Schalk\schalk.key` |
| Archivierte Rechnungen, Belege, Eingangsrechnungen | `%LOCALAPPDATA%\Schalk\app_data`, `...\assets` |
| Protokoll | `%LOCALAPPDATA%\Schalk\schalk.log` |

- Die Datenbank liegt nur im Arbeitsspeicher entschlüsselt vor. Auf der Festplatte steht ausschließlich die verschlüsselte Datei, sie wird im Hintergrund atomar geschrieben.
- Der Schlüssel ist per DPAPI an das Windows-Benutzerkonto gebunden, deshalb gibt es keinen Passwort-Dialog. **Bei einer Neuinstallation von Windows oder einem PC-Wechsel sind die Daten nur über ein Backup wiederherstellbar.** Backups (Einstellungen → Backup) sind mit einem eigenen Backup-Passwort verschlüsselt und lassen sich auf jedem PC einspielen.
- Mit der Umgebungsvariable `SCHALK_DATA_DIR` lässt sich ein anderer Datenordner festlegen.
- Das Programm lässt sich nur einmal gleichzeitig starten.

## E-Rechnung

**Ausgang.** Jede festgeschriebene Rechnung wird als **ZUGFeRD/Factur-X (Profil EN 16931)** erzeugt: ein PDF/A-3 mit eingebettetem XML, eingebetteten Schriften und GiroCode. Vor dem Festschreiben wird geprüft:
- die Pflichtangaben nach § 14 UStG
- die Regeln der EN 16931 (offizielles Schematron, über Saxon-HE)

Zusätzlich lässt sich jede Rechnung als **XRechnung 3.0 (CII)** exportieren. Das ist Pflicht für Behörden, die Leitweg-ID wird im Kundenstamm als Käuferreferenz eingetragen.

**Eingang.** Unter Lieferanten- bzw. Sonstige Rechnungen werden XRechnung (CII und UBL) und ZUGFeRD-PDFs eingelesen. Betrag, Datum, Lieferant und Rechnungsnummer werden übernommen und die Rechnung lesbar angezeigt. Die Originaldatei wird unverändert archiviert.

**Steuerfälle.** Pro Position sind 19 %, 7 % oder 0 % möglich. Bei 0 % ist ein Befreiungsgrund Pflicht, z. B. § 19 UStG, § 13b (Reverse Charge), § 4 Nr. 1b oder § 4 Nr. 1a. Für Kleinunternehmer gibt es eine eigene Einstellung.

## GoBD

- Rechnungen erhalten ihre lückenlose Nummer erst beim Festschreiben. Danach sind sie unveränderbar und werden nur per Stornorechnung korrigiert.
- Rechnungen und Kassenbuch sind über SHA-256-Hash-Ketten gesichert. Archivierte Dateien sind schreibgeschützt und mit Hash gespeichert.
- Kassenbucheinträge werden per Gegenbuchung storniert. Eingangsrechnungen werden storniert, nie gelöscht.
- Jede Aktion wird mit dem Windows-Benutzer protokolliert (Verlauf). Beim Start und unter Einstellungen → Sicherheit & GoBD wird die Integrität geprüft.

## Tests

```powershell
pip install -r requirements-dev.txt
python -m pytest tests
```
