# Beispiel-E-Rechnungen

Von Schalk erzeugte Rechnungen für alle unterstützten Steuerfälle, zum Prüfen mit externen Validatoren. Pro Fall gibt es zwei Dateien:

- `<Fall>.pdf`: **ZUGFeRD/Factur-X** (Profil EN 16931), PDF/A-3 mit eingebettetem XML, genau so, wie Schalk die Rechnung archiviert
- `<Fall>_XRechnung.xml`: **XRechnung 3.0** (CII), wie beim Export

| Fall | Inhalt |
|---|---|
| `Standard_19_7_Rabatt_Gutschrift` | 19 % und 7 %, Positionsrabatt, Gutschrift auf Belegebene |
| `Behoerde_Leitweg-ID` | Rechnung an eine Behörde mit Leitweg-ID |
| `Kleinunternehmer_19_UStG` | Kleinunternehmer ohne Umsatzsteuer (§ 19 UStG) |
| `Steuerfrei_4_UStG` | Steuerfreie Leistung (§ 4 UStG) |
| `Reverse_Charge_13b_UStG` | Steuerschuldnerschaft des Leistungsempfängers (§ 13b UStG), Kunde in Frankreich |
| `Innergemeinschaftliche_Lieferung` | Steuerfreie Lieferung in die EU (§ 4 Nr. 1b UStG), Kunde in den Niederlanden |
| `Ausfuhrlieferung` | Steuerfreie Ausfuhr (§ 4 Nr. 1a UStG), Kunde in der Schweiz |
| `Stornorechnung` | Stornorechnung (Rechnungsart 381) zur Standardrechnung |

Alle Firmen-, Kunden- und Bankdaten sind erfunden.

## Selbst prüfen

- **XRechnung**: offizieller KoSIT-Validator, z. B. online unter https://erechnungsvalidator.service-bw.de
- **ZUGFeRD-PDF komplett** (XML, Profil und PDF/A-3): Mustang-Validator, https://www.mustangproject.org
- **Nur PDF/A-3**: veraPDF, https://verapdf.org

## Neu erzeugen

```powershell
python tools/create_sample_invoices.py
```
