# Schalk

Rechnungs- und Buchhaltungsprogramm für kleine Unternehmen unter **Windows 10/11**: Kundenrechnungen als E-Rechnung (ZUGFeRD/XRechnung), Angebote, Mahnungen, Kassenbuch, Eingangsrechnungen, Kunden und Auswertung. Die Datenhaltung ist GoBD-orientiert.

## Installation

Unter [Releases](https://github.com/niklastheiler/Schalk/releases) das aktuelle `Schalk-Setup-vX.Y.exe` herunterladen und ausführen. Es installiert Schalk nach `C:\Programme\Schalk` (Administratorrechte nötig), legt eine Verknüpfung im Startmenü und auf Wunsch auf dem Desktop an und lässt sich unter „Apps & Features“ wieder deinstallieren. Eine Python-Installation ist nicht nötig. Was sich zwischen den Versionen geändert hat, steht im [Changelog](CHANGELOG.md).

Die Daten liegen getrennt vom Programm in `%LOCALAPPDATA%\Schalk`. Installation, Updates und Deinstallation lassen sie unberührt.

### Automatische Updates

Ab Version 1.2 prüft Schalk bei jedem Start im Hintergrund, ob es auf GitHub ein neueres Release gibt. Ist eines da, erscheint ein kurzer Hinweis, und das neue Setup wird im Hintergrund heruntergeladen und per SHA-256 geprüft. Danach fragt Schalk, ob es jetzt neu starten soll. Beim Neustart (oder sonst beim nächsten Schließen) läuft das Setup still, Windows fragt dabei einmal nach der Berechtigung, und die neue Version startet. Lehnt man die Abfrage ab, bleibt alles unverändert und das Update wird beim nächsten Start erneut angeboten. Beim Start aus dem Quellcode wird nichts aktualisiert.

## Start aus dem Quellcode

Voraussetzung: **Python 3.14** (64 Bit) von python.org. Python 3.15 wird noch nicht unterstützt, weil Saxon-HE (EN-16931-Prüfung) dafür noch kein Paket anbietet.

```powershell
git clone https://github.com/niklastheiler/Schalk.git
cd Schalk
py -3.14 -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py
```

## Programm als EXE bauen

```powershell
build.bat
```

Das Skript legt eine virtuelle Umgebung an, führt die Tests aus und erzeugt `dist\Schalk\Schalk.exe`. Das Setup baut der Release-Workflow daraus mit Inno Setup (`installer/schalk.iss`).

## Neue Version veröffentlichen

1. Version und Changelog vorbereiten, z. B. für ein Patch-Release nach einem Sicherheitsupdate:
   ```powershell
   python tools/bump_version.py 1.1.1 "Sicherheitsupdate: cryptography 50.0.1"
   ```
   Das setzt `APP_VERSION` in `src/version.py` und legt den Abschnitt in `CHANGELOG.md` an (jeder Text wird ein Eintrag). Die neue Version muss größer sein als die aktuelle.
2. Nach dem Merge auf `main` unter GitHub → Actions → Release → „Run workflow“ starten (oder einen Tag pushen, z. B. `git tag v1.1` und `git push origin v1.1`).
3. Der Workflow `.github/workflows/release.yml` führt zuerst die komplette E-Rechnungs-Prüfung aus (Tests und Mustang-Validator für alle Steuerfälle). Nur wenn sie besteht, baut er die EXE unter Windows (inklusive Tests), baut daraus das Setup, testet es mit einer stillen Installation und Deinstallation und veröffentlicht das Release mit Setup und Changelog-Abschnitt.

## Datenablage und Sicherheit

| Was | Wo |
|---|---|
| Datenbank (verschlüsselt) | `%LOCALAPPDATA%\Schalk\schalk.enc.db` |
| Schlüssel (Windows-DPAPI) | `%LOCALAPPDATA%\Schalk\schalk.key` |
| Archivierte Rechnungen, Belege, Eingangsrechnungen | `%LOCALAPPDATA%\Schalk\app_data`, `...\assets` |
| Protokoll | `%LOCALAPPDATA%\Schalk\schalk.log` |

- Die Datenbank liegt nur im Arbeitsspeicher entschlüsselt vor. Auf der Festplatte steht ausschließlich die verschlüsselte Datei, sie wird im Hintergrund atomar geschrieben.
- Der Schlüssel ist per DPAPI an das Windows-Benutzerkonto gebunden, deshalb gibt es keinen Passwort-Dialog. **Bei einer Neuinstallation von Windows oder einem PC-Wechsel sind die Daten nur über ein Backup wiederherstellbar.** Backups (Einstellungen → Sicherheit & GoBD) sind eine einzelne `.backup`-Datei mit Datenbank und allen archivierten Dokumenten. Sie ist mit einem eigenen Backup-Passwort verschlüsselt (AES-256-GCM) und lässt sich auf jedem PC einspielen.
- Mit der Umgebungsvariable `SCHALK_DATA_DIR` lässt sich ein anderer Datenordner festlegen.
- Das Programm lässt sich nur einmal gleichzeitig starten.

## E-Rechnung

**Ausgang.** Jede festgeschriebene Rechnung wird als **ZUGFeRD/Factur-X (Profil EN 16931)** erzeugt: ein PDF/A-3 mit eingebettetem XML und eingebetteten Schriften. Vor dem Festschreiben wird geprüft:
- die Pflichtangaben nach § 14 UStG
- die Regeln der EN 16931 (offizielles Schematron, über Saxon-HE)

Zusätzlich lässt sich jede Rechnung als **XRechnung 3.0 (CII)** exportieren. Das ist Pflicht für Behörden, die Leitweg-ID wird im Kundenstamm als Käuferreferenz eingetragen.

**Eingang.** Unter Lieferanten- bzw. Sonstige Rechnungen werden XRechnung (CII und UBL) und ZUGFeRD-PDFs eingelesen. Betrag, Datum, Lieferant und Rechnungsnummer werden übernommen und die Rechnung lesbar angezeigt. Die Originaldatei wird unverändert archiviert.

**Steuerfälle.** Pro Position sind 19 %, 7 % oder 0 % möglich. Bei 0 % ist ein Befreiungsgrund Pflicht, z. B. § 19 UStG, § 13b (Reverse Charge), § 4 Nr. 1b oder § 4 Nr. 1a. Für Kleinunternehmer gibt es eine eigene Einstellung.

## GoBD

- Rechnungen erhalten ihre lückenlose Nummer erst beim Festschreiben. Danach sind sie unveränderbar und werden nur per Stornorechnung korrigiert.
- Rechnungen und Kassenbuch sind über SHA-256-Hash-Ketten gesichert. Archivierte Dateien sind schreibgeschützt und mit Hash gespeichert.
- Kassenbucheinträge sind zunächst Entwürfe und lassen sich bearbeiten oder löschen. Mit „Festschreiben“ erhalten sie ihre Belegnummer und kommen in die Hash-Kette. Danach werden sie nur noch per Gegenbuchung storniert. Eingangsrechnungen werden storniert, nie gelöscht.
- Jede Aktion wird mit dem Windows-Benutzer protokolliert (Verlauf). Beim Start und unter Einstellungen → Sicherheit & GoBD wird die Integrität geprüft.

## Prüfregeln aktuell halten

Die offiziellen Prüfregeln (CEN EN 16931, KoSIT XRechnung) liegen unter `src/resources`, ihre Versionen stehen in `src/resources/rules.json`. Ein wöchentlicher Workflow prüft, ob es neuere Versionen gibt, und legt dann ein Issue an. Aktualisiert wird mit:

```powershell
python tools/rule_updates.py --update
```

## Abhängigkeiten

Dependabot schlägt wöchentlich Updates der Python-Pakete und GitHub-Actions als gebündelte PRs vor (`.github/dependabot.yml`). Die PySide6-Pakete werden immer gemeinsam aktualisiert, weil ihre Versionen exakt übereinstimmen müssen. Jeder Update-PR durchläuft die Tests und die E-Rechnungs-Prüfung. Ein Update landet erst mit dem nächsten Release bei den Nutzern; bei Sicherheitsupdates daher zeitnah ein Patch-Release veröffentlichen (siehe „Neue Version veröffentlichen“). Bei Updates von PySide6 oder PySide6-Fluent-Widgets vor dem Merge kurz die Oberfläche unter Windows durchklicken, die automatischen Tests decken sie nur teilweise ab.

## Tests

```powershell
pip install -r requirements-dev.txt
python -m pytest tests
```

## Autor

Niklas Theiler. Die Version steht in `src/version.py` und unter Einstellungen → Sicherheit & GoBD → Über Schalk.

## Lizenz

Der Quellcode von Schalk steht unter der [MIT-Lizenz](LICENSE).

Verwendete Bibliotheken haben eigene Lizenzen. Wichtig für die fertige EXE: [PySide6-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets) steht unter der GPLv3, deshalb gelten für die gebündelte Programmdatei auch deren Bedingungen. PySide6/Qt steht unter der LGPLv3, Saxon-HE unter der MPL 2.0, das Raketen-Symbol stammt aus [Lucide](https://lucide.dev) (ISC).
