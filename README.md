# Divibib-MARC-Reparatur

Repariert fehlerhafte ISO-2709-/MARC21-Exporte aus Divibib, prüft das Ergebnis
mit [pymarc](https://gitlab.com/pymarc/pymarc) und gibt eine normkonforme Datei aus.

Der Export erzeugt zeitweise Sätze ohne Directory, mit falschen Leader-Angaben
und doppelten Satz-Terminatoren. MARC-Werkzeuge lesen daraus null Sätze und
melden dabei keinen Fehler, weil schon die ersten fünf Bytes – die Satzlänge –
unlesbar sind.

## Installation

```bash
pip install -r requirements.txt
```

## Verwendung

Kommandozeile:

```bash
python fix_marc.py export.mrc export_fixed.mrc
```

```bash
python fix_marc.py --pruefen export_fixed.mrc
```

Rückgabewert `0` = konform, `1` = Prüfung fehlgeschlagen, `2` = Aufruffehler.

Weboberfläche mit Upload und Download:

```bash
streamlit run app.py
```

Die App verarbeitet ausschließlich im Arbeitsspeicher – kein Schreiben auf die
Platte, kein Cache, keine Session-Ablage.

## Zwei getrennte Prüfebenen

**Formal (`validate_bytes`)** – entscheidet über den Rückgabewert. Geprüft wird,
ob pymarc jeden Satz dekodiert, ob `Record.as_marc()` byte-identisch zum
gelesenen Satz ist (das deckt falsche Satzlängen, eine falsche Base Address und
überzählige Terminatoren auf), sowie Leader Pos. 09/20–23, die Pflichtfelder 001
und 245 und die Länge von Feld 008.

**Inhaltlich (`check_content`)** – reine Hinweise, ohne Einfluss auf den
Rückgabewert. Meldet fehlende oder mehrfach vergebene Satz-IDs in Feld 001,
mehrfache Divibib-Kennungen in 035$a und leere Titel. Eine formal einwandfreie
MARC21-Datei kann Daten enthalten, die einen Löschlauf über Feld 001 unbrauchbar
machen – etwa den Platzhalter `UNKNOWN` statt einer Satz-ID.

## Lizenz

MIT – siehe [LICENSE](LICENSE). Nutzung, Änderung und Weitergabe sind frei,
sofern der Copyright-Hinweis erhalten bleibt.

## Haftungsausschluss

Die Software wird **ohne jede Gewährleistung** bereitgestellt („as is"), wie in
der MIT-Lizenz festgehalten. Das gilt ausdrücklich auch für die Datenqualität:

- Es wird **nicht zugesichert**, dass eine reparierte Datei inhaltlich korrekt,
  vollständig oder für einen bestimmten Zweck geeignet ist. Das Werkzeug stellt
  die Satzstruktur wieder her, es kann fehlende oder falsche Daten weder
  erkennen noch ergänzen.
- Die Prüfung mit pymarc belegt die **formale** Konformität zu MARC21/ISO 2709.
  Sie ist keine Aussage über die Richtigkeit der bibliografischen Angaben.
- Für **Schäden jeder Art**, die aus der Nutzung entstehen – insbesondere durch
  fehlerhafte, unvollständige oder versehentlich gelöschte Katalogdaten –
  übernehmen die Autoren und Rechteinhaber keine Haftung.

Vor einem produktiven Import gehören die Ergebnisse geprüft und der Zielbestand
gesichert.
