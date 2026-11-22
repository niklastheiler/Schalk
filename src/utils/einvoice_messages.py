"""
German messages for the rules of the e-invoice validation (EN 16931, XRechnung, Factur-X).

The official Schematron files report violated rules in English (XRechnung partly in German with English
element names). Every rule is shown in German: the business rules (BR-*) are translated, technical syntax
rules (CII-SR-*, CII-DT-*, FX-SCH-*, PEPPOL-*) can only be caused by the program itself and get a German
message naming the affected information.
"""
import re

# German names of the business terms (BT) and groups (BG) of EN 16931, as in the German XRechnung specification
TERMS = {
    "BG-3": "Vorausgegangene Rechnung", "BG-4": "Verkäufer", "BG-5": "Anschrift des Verkäufers",
    "BG-6": "Kontaktdaten des Verkäufers", "BG-8": "Anschrift des Käufers", "BG-10": "Zahlungsempfänger",
    "BG-11": "Steuervertreter des Verkäufers", "BG-12": "Anschrift des Steuervertreters",
    "BG-14": "Leistungszeitraum", "BG-15": "Lieferanschrift", "BG-16": "Zahlungsanweisungen",
    "BG-17": "Überweisung", "BG-18": "Kartenzahlung", "BG-19": "Lastschrift",
    "BG-20": "Nachlass auf Dokumentenebene", "BG-21": "Zuschlag auf Dokumentenebene",
    "BG-23": "Umsatzsteueraufschlüsselung", "BG-24": "Rechnungsbegründende Unterlage", "BG-25": "Rechnungsposition",
    "BG-26": "Leistungszeitraum der Position", "BG-27": "Nachlass auf Positionsebene",
    "BG-28": "Zuschlag auf Positionsebene", "BG-32": "Artikeleigenschaften",
    "BT-1": "Rechnungsnummer", "BT-2": "Rechnungsdatum", "BT-3": "Rechnungsart", "BT-5": "Rechnungswährung",
    "BT-6": "Währung für die Umsatzsteuer", "BT-7": "Steuerfälligkeitsdatum", "BT-8": "Code für das Steuerfälligkeitsdatum",
    "BT-10": "Käuferreferenz (Leitweg-ID)", "BT-12": "Vertragsnummer", "BT-17": "Vergabe- oder Losnummer",
    "BT-20": "Zahlungsbedingungen", "BT-24": "Spezifikationskennung", "BT-25": "Nummer der vorausgegangenen Rechnung",
    "BT-27": "Name des Verkäufers", "BT-29": "Kennung des Verkäufers", "BT-30": "Registernummer des Verkäufers",
    "BT-31": "USt-IdNr. des Verkäufers", "BT-32": "Steuernummer des Verkäufers",
    "BT-34": "Elektronische Adresse des Verkäufers", "BT-37": "Ort des Verkäufers", "BT-38": "PLZ des Verkäufers",
    "BT-40": "Ländercode des Verkäufers", "BT-41": "Ansprechpartner des Verkäufers",
    "BT-42": "Telefonnummer des Verkäufers", "BT-43": "E-Mail-Adresse des Verkäufers", "BT-44": "Name des Käufers",
    "BT-46": "Kennung des Käufers", "BT-47": "Registernummer des Käufers", "BT-48": "USt-IdNr. des Käufers",
    "BT-49": "Elektronische Adresse des Käufers", "BT-52": "Ort des Käufers", "BT-53": "PLZ des Käufers",
    "BT-55": "Ländercode des Käufers", "BT-56": "Ansprechpartner des Käufers", "BT-59": "Name des Zahlungsempfängers",
    "BT-62": "Name des Steuervertreters", "BT-63": "USt-IdNr. des Steuervertreters",
    "BT-69": "Ländercode des Steuervertreters", "BT-72": "Leistungsdatum", "BT-73": "Beginn des Leistungszeitraums",
    "BT-74": "Ende des Leistungszeitraums", "BT-77": "Ort der Lieferanschrift", "BT-78": "PLZ der Lieferanschrift",
    "BT-80": "Ländercode der Lieferanschrift", "BT-81": "Code für die Zahlungsart", "BT-82": "Zahlungsart (Text)",
    "BT-83": "Verwendungszweck", "BT-84": "IBAN bzw. Kontonummer", "BT-86": "BIC", "BT-87": "Kartennummer",
    "BT-90": "Gläubiger-Identifikationsnummer", "BT-91": "IBAN des belasteten Kontos",
    "BT-92": "Betrag des Nachlasses", "BT-93": "Grundbetrag des Nachlasses", "BT-95": "Umsatzsteuerkategorie des Nachlasses",
    "BT-96": "Umsatzsteuersatz des Nachlasses", "BT-97": "Grund des Nachlasses", "BT-98": "Code für den Grund des Nachlasses",
    "BT-99": "Betrag des Zuschlags", "BT-100": "Grundbetrag des Zuschlags", "BT-102": "Umsatzsteuerkategorie des Zuschlags",
    "BT-103": "Umsatzsteuersatz des Zuschlags", "BT-104": "Grund des Zuschlags", "BT-105": "Code für den Grund des Zuschlags",
    "BT-106": "Summe der Nettobeträge der Positionen", "BT-107": "Summe der Nachlässe", "BT-108": "Summe der Zuschläge",
    "BT-109": "Gesamtbetrag ohne Umsatzsteuer", "BT-110": "Umsatzsteuer gesamt",
    "BT-111": "Umsatzsteuer gesamt in Buchungswährung", "BT-112": "Gesamtbetrag mit Umsatzsteuer",
    "BT-113": "Bereits gezahlter Betrag", "BT-114": "Rundungsbetrag", "BT-115": "Fälliger Zahlungsbetrag",
    "BT-116": "Steuerbemessungsgrundlage", "BT-117": "Umsatzsteuerbetrag der Kategorie",
    "BT-118": "Umsatzsteuerkategorie", "BT-119": "Umsatzsteuersatz der Kategorie",
    "BT-120": "Befreiungsgrund (Text)", "BT-121": "Code für den Befreiungsgrund", "BT-122": "Kennung der Unterlage",
    "BT-124": "Speicherort der externen Unterlage", "BT-125": "Angehängte Unterlage", "BT-126": "Positionsnummer",
    "BT-129": "Menge", "BT-130": "Einheit", "BT-131": "Nettobetrag der Position",
    "BT-134": "Beginn des Leistungszeitraums der Position", "BT-135": "Ende des Leistungszeitraums der Position",
    "BT-136": "Betrag des Positionsnachlasses", "BT-137": "Grundbetrag des Positionsnachlasses",
    "BT-139": "Grund des Positionsnachlasses", "BT-140": "Code für den Grund des Positionsnachlasses",
    "BT-141": "Betrag des Positionszuschlags", "BT-142": "Grundbetrag des Positionszuschlags",
    "BT-144": "Grund des Positionszuschlags", "BT-145": "Code für den Grund des Positionszuschlags",
    "BT-146": "Nettopreis", "BT-148": "Bruttopreis", "BT-149": "Basismenge zum Preis", "BT-150": "Einheit der Basismenge",
    "BT-151": "Umsatzsteuerkategorie der Position", "BT-152": "Umsatzsteuersatz der Position",
    "BT-153": "Bezeichnung der Position", "BT-157": "Artikelkennung (Standard)", "BT-158": "Artikelklassifizierung",
    "BT-160": "Name der Artikeleigenschaft", "BT-161": "Wert der Artikeleigenschaft",
}

RULES = {
    "BR-01": "Die Spezifikationskennung (BT-24) fehlt.",
    "BR-02": "Die Rechnungsnummer (BT-1) fehlt.",
    "BR-03": "Das Rechnungsdatum (BT-2) fehlt.",
    "BR-04": "Die Rechnungsart (BT-3) fehlt.",
    "BR-05": "Die Rechnungswährung (BT-5) fehlt.",
    "BR-06": "Der Name des Verkäufers (BT-27) fehlt. Bitte in den Einstellungen unter Firmendaten eintragen.",
    "BR-07": "Der Name des Kunden (BT-44) fehlt.",
    "BR-08": "Die Anschrift des Verkäufers (BG-5) fehlt. Bitte in den Einstellungen unter Firmendaten eintragen.",
    "BR-09": "Der Ländercode in der Anschrift des Verkäufers (BT-40) fehlt.",
    "BR-10": "Die Anschrift des Kunden (BG-8) fehlt.",
    "BR-11": "Der Ländercode in der Anschrift des Kunden (BT-55) fehlt.",
    "BR-12": "Die Summe der Nettobeträge der Positionen (BT-106) fehlt.",
    "BR-13": "Der Gesamtbetrag ohne Umsatzsteuer (BT-109) fehlt.",
    "BR-14": "Der Gesamtbetrag mit Umsatzsteuer (BT-112) fehlt.",
    "BR-15": "Der fällige Zahlungsbetrag (BT-115) fehlt.",
    "BR-16": "Die Rechnung braucht mindestens eine Position (BG-25).",
    "BR-17": "Weicht der Zahlungsempfänger (BG-10) vom Verkäufer ab, muss sein Name (BT-59) angegeben sein.",
    "BR-18": "Hat der Verkäufer einen Steuervertreter (BG-11), muss dessen Name (BT-62) angegeben sein.",
    "BR-19": "Hat der Verkäufer einen Steuervertreter (BG-11), muss dessen Anschrift (BG-12) angegeben sein.",
    "BR-20": "Die Anschrift des Steuervertreters (BG-12) braucht einen Ländercode (BT-69).",
    "BR-21": "Jede Position (BG-25) braucht eine Positionsnummer (BT-126).",
    "BR-22": "Jede Position (BG-25) braucht eine Menge (BT-129).",
    "BR-23": "Jede Position (BG-25) braucht eine Einheit (BT-130).",
    "BR-24": "Jede Position (BG-25) braucht einen Nettobetrag (BT-131).",
    "BR-25": "Jede Position (BG-25) braucht eine Bezeichnung (BT-153).",
    "BR-26": "Jede Position (BG-25) braucht einen Nettopreis (BT-146).",
    "BR-27": "Der Nettopreis einer Position (BT-146) darf nicht negativ sein.",
    "BR-28": "Der Bruttopreis einer Position (BT-148) darf nicht negativ sein.",
    "BR-29": "Das Ende des Leistungszeitraums (BT-74) darf nicht vor seinem Beginn (BT-73) liegen.",
    "BR-30": "Das Ende des Leistungszeitraums einer Position (BT-135) darf nicht vor seinem Beginn (BT-134) liegen.",
    "BR-31": "Jeder Nachlass auf Dokumentenebene (BG-20) braucht einen Betrag (BT-92).",
    "BR-32": "Jeder Nachlass auf Dokumentenebene (BG-20) braucht eine Umsatzsteuerkategorie (BT-95).",
    "BR-33": "Jeder Nachlass auf Dokumentenebene (BG-20) braucht einen Grund (BT-97) oder einen Code für den Grund (BT-98).",
    "BR-36": "Jeder Zuschlag auf Dokumentenebene (BG-21) braucht einen Betrag (BT-99).",
    "BR-37": "Jeder Zuschlag auf Dokumentenebene (BG-21) braucht eine Umsatzsteuerkategorie (BT-102).",
    "BR-38": "Jeder Zuschlag auf Dokumentenebene (BG-21) braucht einen Grund (BT-104) oder einen Code für den Grund (BT-105).",
    "BR-41": "Jeder Nachlass auf Positionsebene (BG-27) braucht einen Betrag (BT-136).",
    "BR-42": "Jeder Nachlass auf Positionsebene (BG-27) braucht einen Grund (BT-139) oder einen Code für den Grund (BT-140).",
    "BR-43": "Jeder Zuschlag auf Positionsebene (BG-28) braucht einen Betrag (BT-141).",
    "BR-44": "Jeder Zuschlag auf Positionsebene (BG-28) braucht einen Grund (BT-144) oder einen Code für den Grund (BT-145).",
    "BR-45": "Jede Umsatzsteueraufschlüsselung (BG-23) braucht eine Steuerbemessungsgrundlage (BT-116).",
    "BR-46": "Jede Umsatzsteueraufschlüsselung (BG-23) braucht einen Umsatzsteuerbetrag (BT-117).",
    "BR-47": "Jede Umsatzsteueraufschlüsselung (BG-23) braucht eine Umsatzsteuerkategorie (BT-118).",
    "BR-48": "Jede Umsatzsteueraufschlüsselung (BG-23) braucht einen Steuersatz (BT-119), außer die Rechnung unterliegt nicht der Umsatzsteuer.",
    "BR-49": "Die Zahlungsanweisung (BG-16) braucht einen Code für die Zahlungsart (BT-81).",
    "BR-50": "Bei Zahlung per Überweisung (BG-17) muss die IBAN (BT-84) angegeben sein. Bitte in den Einstellungen unter Bankdaten eintragen.",
    "BR-51": "Eine Kartennummer (BT-87) darf nie vollständig in der Rechnung stehen, höchstens die ersten 6 und die letzten 4 Ziffern.",
    "BR-52": "Jede rechnungsbegründende Unterlage (BG-24) braucht eine Kennung (BT-122).",
    "BR-53": "Ist eine Währung für die Umsatzsteuer (BT-6) angegeben, muss die Umsatzsteuer gesamt in dieser Währung (BT-111) angegeben sein.",
    "BR-54": "Jede Artikeleigenschaft (BG-32) braucht einen Namen (BT-160) und einen Wert (BT-161).",
    "BR-55": "Jeder Verweis auf eine vorausgegangene Rechnung (BG-3) braucht deren Nummer (BT-25).",
    "BR-56": "Der Steuervertreter des Verkäufers (BG-11) braucht eine USt-IdNr. (BT-63).",
    "BR-57": "Die Lieferanschrift (BG-15) braucht einen Ländercode (BT-80).",
    "BR-61": "Bei Zahlung per Überweisung muss die IBAN bzw. Kontonummer (BT-84) angegeben sein. Bitte in den Einstellungen unter Bankdaten eintragen.",
    "BR-62": "Die elektronische Adresse des Verkäufers (BT-34) braucht eine Schema-Kennung.",
    "BR-63": "Die elektronische Adresse des Kunden (BT-49) braucht eine Schema-Kennung.",
    "BR-64": "Die Artikelkennung (BT-157) braucht eine Schema-Kennung.",
    "BR-65": "Die Artikelklassifizierung (BT-158) braucht eine Schema-Kennung.",
    "BR-B-01": "Die Umsatzsteuerkategorie „Split payment“ ist nur in inländischen italienischen Rechnungen zulässig.",
    "BR-B-02": "Eine Rechnung mit der Umsatzsteuerkategorie „Split payment“ darf keine Beträge mit dem Regelsteuersatz enthalten.",
    "BR-CO-03": "Steuerfälligkeitsdatum (BT-7) und Code für das Steuerfälligkeitsdatum (BT-8) dürfen nicht beide angegeben sein.",
    "BR-CO-04": "Jede Position (BG-25) braucht eine Umsatzsteuerkategorie (BT-151).",
    "BR-CO-05": "Code (BT-98) und Text (BT-97) für den Grund eines Nachlasses müssen dasselbe bedeuten.",
    "BR-CO-06": "Code (BT-105) und Text (BT-104) für den Grund eines Zuschlags müssen dasselbe bedeuten.",
    "BR-CO-07": "Code (BT-140) und Text (BT-139) für den Grund eines Positionsnachlasses müssen dasselbe bedeuten.",
    "BR-CO-08": "Code (BT-145) und Text (BT-144) für den Grund eines Positionszuschlags müssen dasselbe bedeuten.",
    "BR-CO-09": "Jede USt-IdNr. (BT-31, BT-63, BT-48) muss mit dem Ländercode beginnen, z. B. DE (Griechenland: EL).",
    "BR-CO-10": "Die Summe der Nettobeträge (BT-106) stimmt nicht mit der Summe der Positionen (BT-131) überein.",
    "BR-CO-11": "Die Summe der Nachlässe (BT-107) stimmt nicht mit den einzelnen Nachlässen (BT-92) überein.",
    "BR-CO-12": "Die Summe der Zuschläge (BT-108) stimmt nicht mit den einzelnen Zuschlägen (BT-99) überein.",
    "BR-CO-13": "Der Gesamtbetrag ohne Umsatzsteuer (BT-109) muss der Summe der Positionen minus Nachlässe plus Zuschläge entsprechen.",
    "BR-CO-14": "Die Umsatzsteuer gesamt (BT-110) muss der Summe der Umsatzsteuerbeträge je Kategorie (BT-117) entsprechen.",
    "BR-CO-15": "Der Gesamtbetrag mit Umsatzsteuer (BT-112) muss dem Betrag ohne Umsatzsteuer (BT-109) plus Umsatzsteuer (BT-110) entsprechen.",
    "BR-CO-16": "Der fällige Betrag (BT-115) muss dem Gesamtbetrag (BT-112) minus bereits gezahltem Betrag (BT-113) plus Rundungsbetrag (BT-114) entsprechen.",
    "BR-CO-17": "Der Umsatzsteuerbetrag einer Kategorie (BT-117) muss Bemessungsgrundlage (BT-116) mal Steuersatz (BT-119) sein, auf 2 Nachkommastellen gerundet.",
    "BR-CO-18": "Die Rechnung braucht mindestens eine Umsatzsteueraufschlüsselung (BG-23).",
    "BR-CO-19": "Ist ein Leistungszeitraum (BG-14) angegeben, muss sein Beginn (BT-73) oder sein Ende (BT-74) angegeben sein.",
    "BR-CO-20": "Ist ein Leistungszeitraum einer Position (BG-26) angegeben, muss sein Beginn (BT-134) oder sein Ende (BT-135) angegeben sein.",
    "BR-CO-21": "Jeder Nachlass auf Dokumentenebene (BG-20) braucht einen Grund (BT-97) oder einen Code für den Grund (BT-98).",
    "BR-CO-22": "Jeder Zuschlag auf Dokumentenebene (BG-21) braucht einen Grund (BT-104) oder einen Code für den Grund (BT-105).",
    "BR-CO-23": "Jeder Nachlass auf Positionsebene (BG-27) braucht einen Grund (BT-139) oder einen Code für den Grund (BT-140).",
    "BR-CO-24": "Jeder Zuschlag auf Positionsebene (BG-28) braucht einen Grund (BT-144) oder einen Code für den Grund (BT-145).",
    "BR-CO-26": "Damit der Kunde den Verkäufer eindeutig erkennt, muss eine Kennung des Verkäufers (BT-29), eine Registernummer (BT-30) "
                "oder eine USt-IdNr. (BT-31) angegeben sein. Bitte in den Einstellungen unter Firmendaten die Steuernummer oder USt-IdNr. eintragen.",
    "BR-TMP-2": "Der Speicherort einer externen Unterlage (BT-124) muss eine vollständige Internetadresse sein.",
    "BR-TMP-3": "Die Basismenge zum Preis (BT-149) und ihre Einheit (BT-150) müssen bei Netto- und Bruttopreis gleich sein.",
    "BR-TMP-CVD-01": "Die Artikelklassifizierung (BT-158) muss einen Schlüssel aus der Codeliste UNTDID 7143 verwenden.",
    # XRechnung (BR-DE-*): German in the original, but with English element names
    "BR-DE-1": "Die Zahlungsanweisungen (BG-16) fehlen. Bitte in den Einstellungen unter Bankdaten die IBAN eintragen.",
    "BR-DE-2": "Die Kontaktdaten des Verkäufers (BG-6) fehlen. Bitte in den Einstellungen unter Firmendaten eintragen.",
    "BR-DE-3": "Der Ort des Verkäufers (BT-37) fehlt. Bitte in den Einstellungen unter Firmendaten eintragen.",
    "BR-DE-4": "Die PLZ des Verkäufers (BT-38) fehlt. Bitte in den Einstellungen unter Firmendaten eintragen.",
    "BR-DE-5": "Der Ansprechpartner des Verkäufers (BT-41) fehlt. Bitte in den Einstellungen Vor- und Nachname eintragen.",
    "BR-DE-6": "Die Telefonnummer des Verkäufers (BT-42) fehlt. Bitte in den Einstellungen unter Firmendaten eintragen.",
    "BR-DE-7": "Die E-Mail-Adresse des Verkäufers (BT-43) fehlt. Bitte in den Einstellungen unter Firmendaten eintragen.",
    "BR-DE-8": "Der Ort des Kunden (BT-52) fehlt.",
    "BR-DE-9": "Die PLZ des Kunden (BT-53) fehlt.",
    "BR-DE-10": "Bei einer Lieferanschrift (BG-15) muss deren Ort (BT-77) angegeben sein.",
    "BR-DE-11": "Bei einer Lieferanschrift (BG-15) muss deren PLZ (BT-78) angegeben sein.",
    "BR-DE-14": "Der Umsatzsteuersatz der Kategorie (BT-119) fehlt.",
    "BR-DE-15": "Die Käuferreferenz (BT-10) fehlt. Bei Behörden ist das die Leitweg-ID (im Kundenstamm eintragen).",
    "BR-DE-16": "Bei umsatzsteuerpflichtigen Rechnungen muss die USt-IdNr. (BT-31) oder die Steuernummer (BT-32) des Verkäufers "
                "angegeben sein. Bitte in den Einstellungen unter Firmendaten eintragen.",
    "BR-DE-17": "Die Rechnungsart (BT-3) ist für eine XRechnung nicht zulässig.",
    "BR-DE-18": "Die Skonto-Angaben in den Zahlungsbedingungen (BT-20) haben nicht das vorgeschriebene Format.",
    "BR-DE-19": "Die IBAN (BT-84) ist ungültig.",
    "BR-DE-20": "Die IBAN des belasteten Kontos (BT-91) ist ungültig.",
    "BR-DE-21": "Die Spezifikationskennung (BT-24) passt nicht zur XRechnung-Version.",
    "BR-DE-22": "Die Dateinamen der angehängten Unterlagen müssen eindeutig sein.",
    "BR-DE-23-a": "Bei Zahlung per Überweisung müssen die Überweisungsdaten (BG-17) angegeben sein.",
    "BR-DE-23-b": "Bei Zahlung per Überweisung dürfen keine Karten- (BG-18) oder Lastschriftdaten (BG-19) angegeben sein.",
    "BR-DE-24-a": "Bei Kartenzahlung müssen genau einmal Kartendaten (BG-18) angegeben sein.",
    "BR-DE-24-b": "Bei Kartenzahlung dürfen keine Überweisungs- (BG-17) oder Lastschriftdaten (BG-19) angegeben sein.",
    "BR-DE-25-a": "Bei Zahlung per Lastschrift müssen genau einmal Lastschriftdaten (BG-19) angegeben sein.",
    "BR-DE-25-b": "Bei Zahlung per Lastschrift dürfen keine Überweisungs- (BG-17) oder Kartendaten (BG-18) angegeben sein.",
    "BR-DE-26": "Bei einer korrigierten Rechnung muss die vorausgegangene Rechnung (BG-3) angegeben sein.",
    "BR-DE-27": "Die Telefonnummer des Verkäufers (BT-42) muss mindestens drei Ziffern enthalten.",
    "BR-DE-28": "Die E-Mail-Adresse des Verkäufers (BT-43) ist ungültig: Sie braucht genau ein @, davor und danach Zeichen "
                "und einen Punkt in der Domain.",
    "BR-DE-30": "Bei Lastschrift (BG-19) muss die Gläubiger-Identifikationsnummer (BT-90) angegeben sein.",
    "BR-DE-31": "Bei Lastschrift (BG-19) muss die IBAN des belasteten Kontos (BT-91) angegeben sein.",
    "BR-DE-CVD-01": "Die Vertragsnummer (BT-12) fehlt (Pflicht bei sauberen Straßenfahrzeugen).",
    "BR-DE-CVD-02": "Die Vergabe- oder Losnummer (BT-17) fehlt (Pflicht bei sauberen Straßenfahrzeugen).",
    "BR-DE-CVD-03": "Mindestens eine Position braucht die Fahrzeugklassifizierung 'CVD' mit der Eigenschaft 'cva'.",
    "BR-DE-CVD-04": "Die Fahrzeugklassifizierung 'CVD' (BT-158) enthält keine zulässige Fahrzeugkategorie.",
    "BR-DE-CVD-05": "Die Eigenschaft 'cva' (BT-161) enthält keinen zulässigen Wert.",
    "BR-DE-CVD-06-a": "Zur Fahrzeugklassifizierung 'CVD' gehört in derselben Position genau eine Eigenschaft 'cva'.",
    "BR-DE-CVD-06-b": "Zur Eigenschaft 'cva' gehört in derselben Position genau eine Fahrzeugklassifizierung 'CVD'.",
    "BR-DEX-01": "Eine angehängte Unterlage (BT-125) hat ein nicht zulässiges Dateiformat.",
    "BR-DEX-02": "Die Summe der Teilpositionen stimmt nicht mit dem Nettobetrag der übergeordneten Position überein.",
    "BR-DEX-03": "Eine Teilposition braucht dieselbe Umsatzsteuerkategorie wie ihre übergeordnete Position.",
    "BR-DEX-04": "Eine Kennung verwendet ein nicht zulässiges Schema (ISO 6523 ICD).",
    "BR-DEX-05": "Eine Kennung verwendet ein nicht zulässiges Schema (ISO 6523 ICD).",
    "BR-DEX-06": "Eine Kennung verwendet ein nicht zulässiges Schema (ISO 6523 ICD).",
    "BR-DEX-07": "Eine elektronische Adresse verwendet ein nicht zulässiges Schema (CEF EAS).",
    "BR-DEX-08": "Die Kennung des Lieferorts verwendet ein nicht zulässiges Schema (ISO 6523 ICD).",
    "BR-DEX-09": "Teilpositionen sind nur im erweiterten XRechnung-Profil zulässig.",
    # Code lists
    "BR-CL-01": "Die Rechnungsart (BT-3) ist kein zulässiger Code (UNTDID 1001).",
    "BR-CL-03": "Ein Währungscode ist ungültig (ISO 4217, z. B. EUR).",
    "BR-CL-04": "Die Rechnungswährung (BT-5) ist ungültig (ISO 4217, z. B. EUR).",
    "BR-CL-05": "Die Währung für die Umsatzsteuer (BT-6) ist ungültig (ISO 4217, z. B. EUR).",
    "BR-CL-06": "Der Code für das Steuerfälligkeitsdatum (BT-8) ist nicht zulässig (UNTDID 2475).",
    "BR-CL-07": "Das Schema einer Objektkennung ist nicht zulässig (UNTDID 1153).",
    "BR-CL-08": "Der Code für den Betreff einer Bemerkung ist nicht zulässig (UNTDID 4451).",
    "BR-CL-10": "Das Schema einer Kennung ist nicht zulässig (ISO 6523 ICD).",
    "BR-CL-11": "Das Schema einer Registernummer ist nicht zulässig (ISO 6523 ICD).",
    "BR-CL-13": "Das Schema der Artikelklassifizierung (BT-158) ist nicht zulässig (UNTDID 7143).",
    "BR-CL-14": "Ein Ländercode ist ungültig (ISO 3166-1, z. B. DE). Bitte das Land beim Kunden prüfen.",
    "BR-CL-15": "Ein Ländercode ist ungültig (ISO 3166-1, z. B. DE). Bitte das Land beim Kunden prüfen.",
    "BR-CL-16": "Der Code für die Zahlungsart (BT-81) ist nicht zulässig (UNTDID 4461).",
    "BR-CL-17": "Eine Umsatzsteuerkategorie ist nicht zulässig (UNCL 5305).",
    "BR-CL-18": "Eine Umsatzsteuerkategorie ist nicht zulässig (UNCL 5305).",
    "BR-CL-19": "Der Code für den Grund eines Nachlasses ist nicht zulässig (UNCL 5189).",
    "BR-CL-20": "Der Code für den Grund eines Zuschlags ist nicht zulässig (UNCL 7161).",
    "BR-CL-21": "Das Schema der Artikelkennung (BT-157) ist nicht zulässig (ISO 6523 ICD).",
    "BR-CL-22": "Der Code für den Befreiungsgrund (BT-121) ist nicht zulässig (VATEX).",
    "BR-CL-23": "Eine Einheit (BT-130) ist nicht zulässig. Bitte eine übliche Einheit wie Stück, Stunde, kg oder Pauschale verwenden.",
    "BR-CL-24": "Eine angehängte Unterlage hat einen nicht zulässigen Dateityp.",
    "BR-CL-25": "Das Schema einer elektronischen Adresse (BT-34, BT-49) ist nicht zulässig (CEF EAS).",
    "BR-CL-26": "Das Schema der Kennung des Lieferorts ist nicht zulässig (ISO 6523 ICD).",
}

# VAT categories (UNCL 5305) as named in the rule IDs: BR-S-*, BR-Z-*, ...
CATEGORIES = {
    "S": "Regelsteuersatz", "Z": "Nullsatz", "E": "Steuerbefreit", "AE": "Reverse Charge (Steuerschuldnerschaft des Leistungsempfängers)",
    "IC": "Innergemeinschaftliche Lieferung", "G": "Ausfuhrlieferung", "O": "Nicht steuerbar",
    "AF": "IGIC (Kanarische Inseln)", "AG": "IPSI (Ceuta und Melilla)",
}
_CATEGORY_RULES = {
    1: "Enthält die Rechnung Beträge der Kategorie „{c}“, braucht die Umsatzsteueraufschlüsselung (BG-23) diese Kategorie.",
    2: "Bei Positionen der Kategorie „{c}“ {seller}",
    3: "Bei Nachlässen der Kategorie „{c}“ {seller}",
    4: "Bei Zuschlägen der Kategorie „{c}“ {seller}",
    5: "Bei Positionen der Kategorie „{c}“ {rate} (BT-152).",
    6: "Bei Nachlässen der Kategorie „{c}“ {rate} (BT-96).",
    7: "Bei Zuschlägen der Kategorie „{c}“ {rate} (BT-103).",
    8: "Die Steuerbemessungsgrundlage (BT-116) der Kategorie „{c}“ muss der Summe der Positionen minus Nachlässe plus "
       "Zuschläge dieser Kategorie entsprechen.",
    9: "Der Umsatzsteuerbetrag (BT-117) der Kategorie „{c}“ {tax}",
    10: "Die Kategorie „{c}“ {reason}",
    11: "Bei der Kategorie „{c}“ darf die Rechnung keine weiteren Umsatzsteuerkategorien enthalten.",
    12: "Bei der Kategorie „{c}“ müssen alle Positionen diese Kategorie haben.",
    13: "Bei der Kategorie „{c}“ müssen alle Nachlässe diese Kategorie haben.",
    14: "Bei der Kategorie „{c}“ müssen alle Zuschläge diese Kategorie haben.",
}
_SELLER_ID = ("muss die USt-IdNr. (BT-31) oder die Steuernummer (BT-32) des Verkäufers angegeben sein. "
              "Bitte in den Einstellungen unter Firmendaten eintragen.")
_SELLER_AND_BUYER_VAT_ID = ("müssen die USt-IdNr. des Verkäufers (BT-31) und die des Kunden (BT-48) angegeben sein. "
                            "Bitte in den Firmendaten und im Kundenstamm eintragen.")
_SELLER_VAT_ID = "muss die USt-IdNr. des Verkäufers (BT-31) angegeben sein. Bitte in den Einstellungen unter Firmendaten eintragen."
_NO_VAT_ID = "dürfen keine USt-IdNr. von Verkäufer (BT-31) oder Kunde (BT-48) angegeben sein."
_SPECIAL = {
    ("AE", 2): _SELLER_AND_BUYER_VAT_ID, ("AE", 3): _SELLER_AND_BUYER_VAT_ID, ("AE", 4): _SELLER_AND_BUYER_VAT_ID,
    ("IC", 2): _SELLER_AND_BUYER_VAT_ID, ("IC", 3): _SELLER_AND_BUYER_VAT_ID, ("IC", 4): _SELLER_AND_BUYER_VAT_ID,
    ("G", 2): _SELLER_VAT_ID, ("G", 3): _SELLER_VAT_ID, ("G", 4): _SELLER_VAT_ID,
    ("O", 2): _NO_VAT_ID, ("O", 3): _NO_VAT_ID, ("O", 4): _NO_VAT_ID,
    ("IC", 11): "Bei innergemeinschaftlicher Lieferung muss das Leistungsdatum (BT-72) oder der Leistungszeitraum (BG-14) angegeben sein.",
    ("IC", 12): "Bei innergemeinschaftlicher Lieferung muss der Ländercode der Lieferanschrift (BT-80) angegeben sein.",
}


def _category_message(code: str, number: int) -> str:
    c = CATEGORIES[code]
    if code == "IC" and number in (11, 12):
        return _SPECIAL[(code, number)]
    if number in (5, 6, 7):
        if code == "S" or (code == "AF" and number == 5):
            rate = "muss der Steuersatz größer als 0 sein"
        elif code in ("AF", "AG"):
            rate = "darf der Steuersatz nicht negativ sein"
        elif code == "O":
            rate = "darf kein Steuersatz angegeben sein"
        else:
            rate = "muss der Steuersatz 0 % sein"
        return _CATEGORY_RULES[number].format(c=c, rate=rate)
    if number == 9:
        tax = ("muss Bemessungsgrundlage mal Steuersatz sein." if code in ("S", "AF", "AG")
               else "muss 0 sein.")
        return _CATEGORY_RULES[9].format(c=c, tax=tax)
    if number == 10:
        reason = ("darf keinen Befreiungsgrund (BT-120, BT-121) haben." if code in ("S", "Z", "AF", "AG")
                  else "braucht einen Befreiungsgrund (BT-120) oder einen Code dafür (BT-121).")
        return _CATEGORY_RULES[10].format(c=c, reason=reason)
    return _CATEGORY_RULES[number].format(c=c, seller=_SPECIAL.get((code, number), _SELLER_ID))


def _terms(text: str) -> list:
    names = []
    for term in dict.fromkeys(re.findall(r"B[TG]-\d+", text)):
        if term in TERMS:
            names.append(f"{TERMS[term]} ({term})")
    return names


def german_message(rule_id: str, text: str = "") -> str:
    """The violated rule as German text, prefixed with the rule ID."""
    rule_id = (rule_id or "").strip()
    if rule_id in RULES:
        return f"{RULES[rule_id]} [{rule_id}]"
    m = re.fullmatch(r"BR-(S|Z|E|AE|IC|G|O|AF|AG)-(\d+)", rule_id)
    if m and int(m.group(2)) in _CATEGORY_RULES:
        return f"{_category_message(m.group(1), int(m.group(2)))} [{rule_id}]"
    m = re.fullmatch(r"BR-DEC-\d+", rule_id)
    if m:
        terms = _terms(text)
        target = terms[0] if terms else "einen Betrag"
        return f"Für {target} sind höchstens 2 Nachkommastellen erlaubt. [{rule_id}]"
    # Technical rules of the XML structure: only the program can cause them
    terms = _terms(text)
    detail = f" Betroffen: {', '.join(terms)}." if terms else ""
    name = f" [{rule_id}]" if rule_id else ""
    return f"Die E-Rechnung ist technisch fehlerhaft aufgebaut.{detail} Bitte melden Sie diesen Fehler.{name}"
