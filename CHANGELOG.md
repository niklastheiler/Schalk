# Changelog

## 1.4.9

- Ein fehlender Beleg im Archiv wird überall gleich gemeldet und im Protokoll vermerkt (auch im Kassenbuch)

## 1.4.8

- Tabellen: Linien gleichmäßig ein Pixel breit, Zellen einheitlich gefüllt
- Kassenbuch: Spalte Beleg mit ✓/✗, Doppelklick zeigt den Beleg in Schalk
- Neue Rechnungs-PDFs öffnen direkt die Rechnung statt der Anlagen-Leiste

## 1.4.7

- Seitentasten der Maus: Zurück schließt einen offenen Editor oder geht zum vorherigen Reiter, Vor wieder vorwärts
- DATEV Export ist ausgegraut, wenn nichts zu exportieren ist
- Feine Linien zwischen den Zellen aller Tabellen

## 1.4.6

- Lieferanten- und Sonstige Rechnungen: Doppelklick zeigt den Originalbeleg direkt in Schalk
- Belegordner sind gegen Löschen und Umbenennen im Explorer gesperrt
- Upload: Betragsfeld als einfaches Textfeld, leer wenn kein Betrag erkannt wurde; Versicherungs- und Deckungssummen werden nicht mehr als Betrag vorgeschlagen
- Kassenbuch DATEV-Export ohne stornierte Buchungen und ihre Storno-Gegenbuchungen

## 1.4.5.1

- Prüfregeln für E-Rechnungen aktualisiert (EN16931 1.3.17, XRechnung 3.0.2, Mustang 2.26.0)

## 1.4.5

- Behoben: Nach einem Update blieb das Fenster beim ersten Start grau und reagierte nicht. Die Prüfregeln für E-Rechnungen werden jetzt erst beim ersten Festschreiben geladen.
- Die Backup-Erinnerung erscheint erst, wenn das Fenster sichtbar ist.

## 1.4.4

- PDF-Symbol öffnet nur noch „Speichern unter“, ohne dass Adobe Acrobat mit aufgeht
- Die Frage nach ungespeicherten Änderungen kam manchmal, obwohl nur in ein Feld geklickt wurde

## 1.4.3

- Oberfläche fest in 125 % Größe; die Einstellung „Darstellung“ entfällt
- Auswertung: die Monatsbeschriftung „Dez“ wird nicht mehr abgeschnitten

## 1.4.2

- Update: Wurde ein bereits heruntergeladenes Update direkt beim Start mit „Jetzt neu starten“ bestätigt, blieb Schalk ohne Fenster im Hintergrund hängen und das Update wurde nicht installiert
- Update: Andere geöffnete Programme (z. B. Adobe Acrobat) verhindern die Installation nicht mehr

## 1.4.1

- Kassenbuch: Beleg ist Pflicht bei „Einnahme“ und „Barentnahme Firma“ (bei einer Einnahme zu einer Rechnung zählt deren PDF als Beleg)
- Kassenbuch: kompakteres Formular, das Beleg-Feld steht direkt neben der Beschreibung
- Neue Einstellung „Darstellung“: Schriftgröße 100 bis 200 % (wirksam nach Neustart); in schmalen Fenstern bleibt das Menü eingeklappt

## 1.4

- Zahlungen: „Als bezahlt markieren“ fragt das Datum des Zahlungseingangs ab; neue Spalte „Bezahlt am“ bei den Kundenrechnungen. „Teilbezahlt“ gibt es nicht mehr, Rechnungen mit diesem Status sind wieder „Offen“. Eine Rücklastschrift (zurück auf „Offen“) wird nachvollziehbar zurückgebucht
- Kassenbuch: Bei „Einnahme“ lässt sich eine offene Rechnung des laufenden Monats auswählen (Betrag, Text und Rechnungs-PDF werden übernommen); beim Festschreiben wird die Rechnung automatisch „Bezahlt“. „Barentnahme Privat“ hat kein Belegfeld mehr
- Kassenbuch: Ein angefügter Beleg wird ausgewertet (Betrag, Beschreibung, Datum, Einnahme oder Ausgabe)
- Lieferanten- und Sonstige Rechnungen: Lieferant, Rechnungsnummer, Datum und Betrag werden auch aus PDFs ohne E-Rechnung erkannt; das Betragsfeld ist auf kleinen Bildschirmen wieder sichtbar; erhaltene E-Rechnungen werden gegen die EN-16931-Regeln geprüft
- PDF-Symbol neben dem Status zum Drucken von Rechnungen, Angeboten und Mahnungen; „Archivieren“ entfällt bei Rechnungen und Angeboten
- DATEV-Export: alle bezahlten Rechnungen (bisher nur archivierte), ohne stornierte Rechnungen und ihre Stornorechnungen
- Beim Wechsel des Reiters oder Schließen des Programms mit ungespeicherten Eingaben fragt Schalk „Verwerfen“ oder „Bleiben“
- Mahnungen nennen den offenen Betrag und werden als Kopie archiviert
- GoBD: Datenexport für die Betriebsprüfung (Einstellungen → Sicherheit & GoBD), Verlauf und Änderungen an Kunden und Firmendaten manipulationssicher protokolliert, Integritätsprüfung erkennt Lücken in Rechnungs- und Belegnummern
- Festgeschriebene Rechnungen und Kassenbuchungen werden sofort gespeichert; eine Rechnung mit Datum in der Zukunft wird nicht festgeschrieben
- Tabellen zentriert; Datumsfelder werden in schmalen Fenstern nicht mehr überdeckt

## 1.3.2

- E-Rechnung ohne USt-IdNr. (nur Steuernummer, z. B. Kleinunternehmer) lässt sich wieder festschreiben (Fehler BR-CO-26)
- Prüfmeldungen der E-Rechnung immer auf Deutsch, mit Hinweis, was zu tun ist
- Eingabeprüfung: PLZ (in Deutschland 5 Ziffern), Telefonnummer, E-Mail-Adresse und Steuernummer
- Steuernummer: Schrägstriche werden beim Tippen automatisch eingefügt (12/345/67890)
- Die gewählte Farbe gilt jetzt auch für das Programm („Farbe (Programm und Dokumente)“)
- Trennlinie zwischen Kundendaten und Rechnungs-/Angebotsdaten
- Schmale Fenster: Filter und Suche rücken in eine eigene Zeile, Spalten wie „Firma“ werden nicht mehr abgeschnitten
- Technische Basis: Python 3.15, aktualisierte Bibliotheken
- Voraussetzung ist jetzt Windows 11 ab Version 24H2; auf älteren Windows-Versionen lässt sich das Setup nicht mehr installieren

## 1.3.1

- Backup ohne Passwort: eine einzelne Datei, die sich auf jedem PC einspielen lässt; beschädigte oder unvollständige Dateien werden erkannt. Backups aus 1.3 und älter (mit Passwort) lassen sich nicht mehr einspielen, deshalb nach dem Update gleich ein neues Backup erstellen
- Monatliche Backup-Erinnerung beim Start: „Später“ oder „Backup jetzt erstellen“
- Standard-Zahlungsziel lässt sich wieder eintragen (leer = 14 Tage)
- Positionen: Eingabefelder springen beim Überfahren mit der Maus nicht mehr herum
- Beschriftungen wie „Rechnungsdatum“ und „Kunde“ sind wieder gut lesbar
- Datumsauswahl zeigt lange Monatsnamen wie „November“ vollständig
- Menü links beim Start ausgeklappt; Seitentitel „Kundenrechnungen“
- Auswertung ohne Scrollbalken; schmalere Eingabefelder bei Firmen- und Bankdaten; „Vorname“/„Nachname“ statt „Ansprechpartner …“

## 1.3

- Neues Design für Rechnungen, Angebote und Mahnungen nach DIN 5008 (passt in Fensterumschläge), mit eigenem Logo, wählbarer Farbe, Fußzeile mit Bank- und Steuerdaten und Seitenzahlen
- Leistungszeitraum (von – bis) statt eines einzelnen Leistungsdatums, auch in der E-Rechnung
- Backup auf einem anderen PC oder Windows-Benutzer: archivierte Rechnungen, Belege und Logo werden wieder gefunden; beschädigte Backups werden von falschen Passwörtern unterschieden; Backup läuft im Hintergrund
- Preiseingabe: „1.500“ ergibt jetzt 1.500 € (bisher 1,50 €)
- PDFs zeigen polnische, tschechische und ungarische Buchstaben korrekt
- Kassenbuch: Bestand darf an keinem Tag negativ werden, auch nicht durch rückdatierte Buchungen
- Keine falschen GoBD-Warnungen mehr nach Zeitumstellung oder Uhrkorrektur
- Drucken mit Edge als PDF-Programm und fehlende Programme führen nicht mehr zu Fehlerdialogen
- Doppelt hochgeladene Eingangsrechnungen werden erkannt; USt-IdNr. und E-Mail von Kunden werden geprüft
- Startet die Datenbank nicht, kann Schalk leer starten, um ein Backup einzuspielen
- Erstes Festschreiben ohne Wartezeit; weitere Einheiten (Woche, Jahr, kWh u. a.) in der E-Rechnung

## 1.2.3

- Button „Nach Update suchen“ unter Einstellungen → Sicherheit & GoBD, zeigt das Ergebnis der Prüfung an
- Updates werden nach dem Download zuverlässig installiert; vorher werden Datenbank und Schlüssel nach %LOCALAPPDATA%\Schalk\backups gesichert (die letzten 5 bleiben)
- Umstieg von 1.2.x: das Setup von 1.2.3 einmal von Hand installieren, danach aktualisiert sich Schalk selbst

## 1.2.2

- Eigenes Programm-Logo in Rot, Schwarz und Weiß für EXE, Setup, Verknüpfungen und Programmfenster

## 1.2.1

- Fehlerbehebung: Schalk 1.2 startete nach der Installation nicht (fehlende Währungstabelle iso4217 in der EXE)

## 1.2

- Installation per Setup nach C:\Programme\Schalk mit Startmenü-/Desktop-Verknüpfung und Deinstallation über „Apps & Features“; die portable ZIP entfällt
- Automatische Updates: Schalk prüft beim Start im Hintergrund auf ein neues Release, lädt es herunter, prüft es per SHA-256 und installiert es nach Rückfrage beim Neustart
- Umstieg von 1.1.1 oder älter: das Setup von 1.2 einmal von Hand installieren, danach aktualisiert sich Schalk selbst

## 1.1.1

- Sicherheitsupdate: cryptography 50.0.2
- PySide6 6.12, SQLAlchemy 2.1, reportlab 5.1 und weitere aktualisierte Abhängigkeiten
- Build mit PyInstaller 6.22 und aktuellen GitHub-Actions

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

Erste finale Version von Schalk, dem Rechnungs- und Buchhaltungsprogramm für kleine Unternehmen unter Windows.

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
