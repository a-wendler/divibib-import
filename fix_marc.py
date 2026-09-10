#!/usr/bin/env python3
"""
Reparatur und Pruefung kaputter ISO-2709-/MARC21-Dateien aus dem Divibib-Export.

Nutzbar als Kommandozeilenwerkzeug und als Modul (siehe app.py).
Alle Kernfunktionen arbeiten rein im Speicher auf bytes -- es wird nichts
zwischengespeichert und nichts auf die Platte geschrieben.

Behobene Defekte:
  1. fehlendes Directory (Feldtags stehen inline statt im Verzeichnis)
  2. Leader-Positionen 08/09 vertauscht, Entry Map "450 " statt "4500"
  3. Leader-Satzlaenge (Pos. 00-04) und Base Address (12-16) falsch
  4. 0x1D (Record Terminator) zusaetzlich VOR jedem Satz
  5. fehlender 0x1E (Field Terminator) nach dem letzten Feld
  6. Feld 008 mit 41 statt 40 Zeichen (ein Blank zu viel)
  7. Datenfelder mit nur einem statt zwei Indikatoren (035)
  8. Datei endet mit 0x1C statt sauber nach dem letzten 0x1D

Aufruf:
  python fix_marc.py <eingabe> <ausgabe>       reparieren und pruefen
  python fix_marc.py --pruefen <datei>         nur pruefen (beliebige MARC-Datei)
  python fix_marc.py --ohne-pruefung <e> <a>   reparieren ohne Pruefung

Zusaetzlich laeuft eine inhaltliche Plausibilitaetspruefung (fehlende oder
doppelte Satz-IDs, leere Titel) -- das sind keine Formatfehler, koennen einen
Import aber trotzdem unbrauchbar machen.

Abhaengigkeit der Pruefung:  pip install pymarc
Rueckgabewert: 0 = alles in Ordnung, 1 = Pruefung fehlgeschlagen, 2 = Aufruffehler
"""
import collections
import io
import sys

RT = b'\x1d'   # record terminator
FT = b'\x1e'   # field terminator
SF = b'\x1f'   # subfield delimiter
FILE_T = b'\x1c'  # file terminator
CONTROL = ('001', '002', '003', '004', '005', '006', '007', '008', '009')
LEADER_LEN = 24


def split_records(raw):
    """Zerlegt eine Rohdatei in Satz-Chunks, tolerant gegen doppelte 0x1D."""
    return [r for r in raw.rstrip(FILE_T).split(RT) if r.strip(b'\x00' + FILE_T)]


# --------------------------------------------------------------------------
# Diagnose
# --------------------------------------------------------------------------

def analyse(raw):
    """Untersucht eine Rohdatei und liefert einen Befund als dict.

    Rueckgabe:
      saetze         Anzahl erkannter Satz-Chunks
      defekte        Liste von Klartextbefunden
      bereits_gueltig ob pymarc die Datei bereits fehlerfrei liest
      reparierbar    ob das bekannte Divibib-Defektmuster vorliegt
    """
    befund = {'saetze': 0, 'defekte': [], 'bereits_gueltig': False, 'reparierbar': False}
    if not raw:
        befund['defekte'].append("Datei ist leer.")
        return befund

    pruefung = validate_bytes(raw)
    if pruefung['ok'] and pruefung['saetze'] > 0:
        befund['bereits_gueltig'] = True
        befund['saetze'] = pruefung['saetze']
        return befund

    if raw.endswith(FILE_T):
        befund['defekte'].append("Datei endet mit 0x1C (File Terminator) statt nach dem letzten 0x1D.")
    core = raw.rstrip(FILE_T)
    if core.startswith(RT):
        befund['defekte'].append("Ein Record Terminator (0x1D) steht zusaetzlich VOR dem ersten Satz.")
    doppelt = core.count(RT + RT)
    if doppelt:
        befund['defekte'].append("%d doppelte Record Terminatoren zwischen den Saetzen." % doppelt)

    records = split_records(raw)
    befund['saetze'] = len(records)
    if not records:
        befund['defekte'].append("Keine Saetze erkennbar.")
        return befund

    kein_dir = laenge_falsch = entry_map = pos0809 = kein_end_ft = 0
    falsche_008 = fehlende_ind = 0
    inline_tags = 0
    for rec in records:
        ldr = rec[:LEADER_LEN]
        if len(ldr) < LEADER_LEN:
            continue
        if rec[LEADER_LEN:LEADER_LEN + 1] == FT:
            kein_dir += 1                      # direkt hinter dem Leader beginnen Felddaten
        try:
            if int(ldr[0:5]) != len(rec) + 1:
                laenge_falsch += 1
        except ValueError:
            laenge_falsch += 1
        if ldr[20:24] != b'4500':
            entry_map += 1
        if ldr[8:10] == b'a ':
            pos0809 += 1
        if not rec.endswith(FT):
            kein_end_ft += 1
        for chunk in rec[LEADER_LEN:].split(FT):
            if not chunk:
                continue
            if chunk[:3].isdigit():
                inline_tags += 1
            tag = chunk[:3].decode('ascii', 'replace')
            rest = chunk[3:]
            if tag == '008' and len(rest) != 40:
                falsche_008 += 1
            elif tag.isdigit() and tag >= '010':
                i = rest.find(SF)
                if 0 <= i < 2:
                    fehlende_ind += 1

    n = len(records)
    if kein_dir:
        befund['defekte'].append(
            "%d/%d Saetze ohne Directory -- die Feldtags stehen inline vor den Daten." % (kein_dir, n))
    if laenge_falsch:
        befund['defekte'].append(
            "%d/%d Saetze mit falscher Satzlaenge im Leader (Pos. 00-04)." % (laenge_falsch, n))
    if pos0809:
        befund['defekte'].append(
            "%d/%d Saetze mit vertauschten Leader-Positionen 08/09 ('a ' statt ' a')." % (pos0809, n))
    if entry_map:
        befund['defekte'].append(
            "%d/%d Saetze mit falscher Entry Map (Leader Pos. 20-23, erwartet '4500')." % (entry_map, n))
    if kein_end_ft:
        befund['defekte'].append(
            "%d/%d Saetze ohne Field Terminator (0x1E) nach dem letzten Feld." % (kein_end_ft, n))
    if falsche_008:
        befund['defekte'].append("%d Felder 008 mit abweichender Laenge (erwartet 40 Zeichen)." % falsche_008)
    if fehlende_ind:
        befund['defekte'].append("%d Datenfelder mit weniger als zwei Indikatoren." % fehlende_ind)

    if pruefung['fehler']:
        befund['defekte'].append("pymarc meldet: %s" % pruefung['fehler'][0])

    # Das bekannte Divibib-Muster: kein Directory, aber Tags inline vorhanden.
    befund['reparierbar'] = kein_dir >= n and inline_tags > 0
    return befund


# --------------------------------------------------------------------------
# Reparatur
# --------------------------------------------------------------------------

def fix_008(data, recno, warn):
    """008 muss exakt 40 Zeichen lang sein."""
    if len(data) == 40:
        return data
    if len(data) > 40:
        # ueberzaehlige Blanks aus dem Blank-Block 11..17 entfernen
        out = bytearray(data)
        i = 11
        while len(out) > 40 and i < len(out) and out[i:i + 1] == b' ':
            del out[i]
        if len(out) != 40:
            out = bytearray(data[:40])
            warn.append("Satz %d: 008 hart auf 40 Zeichen gekuerzt" % recno)
        return bytes(out)
    warn.append("Satz %d: 008 zu kurz (%d), mit Blanks aufgefuellt" % (recno, len(data)))
    return data.ljust(40, b' ')


def parse_record(raw, recno, warn):
    """Zerlegt einen 'kaputten' Satz in (leader, [(tag, felddaten), ...])."""
    leader = raw[:LEADER_LEN]
    fields = []
    for chunk in raw[LEADER_LEN:].split(FT):
        if not chunk:
            continue
        tag = chunk[:3].decode('ascii', 'replace')
        rest = chunk[3:]
        if tag in CONTROL:
            if tag == '008':
                rest = fix_008(rest, recno, warn)
            fields.append((tag, rest))
        else:
            # Indikatoren: alles vor dem ersten Subfeld-Delimiter
            i = rest.find(SF)
            if i < 0:
                warn.append("Satz %d: Feld %s ohne Subfeld" % (recno, tag))
                ind, data = b'  ', rest
            else:
                ind, data = rest[:i], rest[i:]
                if len(ind) < 2:
                    ind = ind.ljust(2, b' ')       # fehlender 2. Indikator
                elif len(ind) > 2:
                    warn.append("Satz %d: Feld %s hat %d Indikatoren" % (recno, tag, len(ind)))
                    ind = ind[:2]
            fields.append((tag, ind + data))
    return leader, fields


def build_record(leader, fields):
    """Baut einen normkonformen ISO-2709-Satz mit Directory.

    Aufbau: Leader(24) + Directory + 0x1E + Felddaten(je mit 0x1E) + 0x1D
    Hinter dem letzten Feld steht KEIN zusaetzlicher 0x1E -- der Terminator
    des letzten Feldes schliesst den Datenteil ab.
    """
    directory = bytearray()
    data = bytearray()
    for tag, value in fields:
        blob = value + FT
        directory += ("%3s%04d%05d" % (tag, len(blob), len(data))).encode('ascii')
        data += blob

    base = LEADER_LEN + len(directory) + 1        # +1 fuer 0x1E hinter dem Directory
    total = base + len(data) + 1                  # +1 fuer den Record Terminator

    ldr = bytearray(b' ' * LEADER_LEN)
    ldr[0:5] = ("%05d" % total).encode('ascii')
    ldr[5:8] = leader[5:8] if len(leader) >= 8 else b'dam'   # Status/Typ/Bibl.-Ebene
    ldr[8] = ord(' ')                             # Type of control
    ldr[9] = ord('a')                             # Zeichenkodierung = UTF-8
    ldr[10:12] = b'22'                            # Indikator- / Subfeldcode-Laenge
    ldr[12:17] = ("%05d" % base).encode('ascii')
    ldr[17:20] = b'   '                           # Encoding level / Kat.-Form / Multipart
    ldr[20:24] = b'4500'                          # Entry Map
    return bytes(ldr) + bytes(directory) + FT + bytes(data) + RT


def repair_bytes(raw):
    """Repariert eine Rohdatei im Speicher.

    Rueckgabe: (ausgabe_bytes, {'gelesen': int, 'geschrieben': int, 'warnungen': [str]})
    """
    warn = []
    records = split_records(raw)
    out = bytearray()
    written = 0
    for n, rec in enumerate(records, 1):
        leader, fields = parse_record(rec, n, warn)
        if not fields:
            warn.append("Satz %d: keine Felder, uebersprungen" % n)
            continue
        out += build_record(leader, fields)
        written += 1
    return bytes(out), {'gelesen': len(records), 'geschrieben': written, 'warnungen': warn}


# --------------------------------------------------------------------------
# Pruefung mit pymarc
# --------------------------------------------------------------------------

def validate_bytes(data, erwartet=None):
    """Prueft MARC-Daten im Speicher mit pymarc auf MARC21-Konformitaet.

    Geprueft wird:
      * pymarc dekodiert jeden Satz ohne Exception
      * Roundtrip: Record.as_marc() ist byte-identisch zum gelesenen Satz.
        Das deckt falsche Satzlaengen, eine falsche Base Address, ein
        inkonsistentes Directory und ueberzaehlige Terminatoren auf.
      * Leader Pos. 09 = 'a' (UTF-8), Pos. 20-23 = '4500'
      * Pflichtfelder 001 und 245 vorhanden, 008 exakt 40 Zeichen
      * Satzzahl entspricht der Erwartung

    Rueckgabe: {'ok': bool, 'saetze': int, 'fehler': [str], 'warnungen': [str],
                'verfuegbar': bool}
    """
    ergebnis = {'ok': False, 'saetze': 0, 'fehler': [], 'warnungen': [], 'verfuegbar': True}
    try:
        from pymarc import MARCReader
    except ImportError:
        ergebnis['verfuegbar'] = False
        ergebnis['fehler'].append("pymarc ist nicht installiert (pip install pymarc).")
        return ergebnis

    fehler = ergebnis['fehler']
    warnungen = ergebnis['warnungen']
    n = 0

    reader = MARCReader(io.BytesIO(data), to_unicode=True, force_utf8=True)
    while True:
        try:
            rec = next(reader)
        except StopIteration:
            break
        except Exception as e:                    # FatalReaderError o.ae.
            fehler.append("nach Satz %d: Lesen abgebrochen -- %s: %s"
                          % (n, type(e).__name__, e))
            break

        n += 1
        if rec is None:
            chunk = reader.current_chunk or b''
            fehler.append("Satz %d: nicht dekodierbar -- %s: %s | Rohdaten: %r"
                          % (n, type(reader.current_exception).__name__,
                             reader.current_exception, chunk[:40]))
            continue

        roh = reader.current_chunk
        neu = rec.as_marc()
        if neu != roh:
            fehler.append("Satz %d: Roundtrip weicht ab -- Leader in der Datei %r, "
                          "von pymarc berechnet %r (%d vs. %d Bytes)"
                          % (n, roh[:24], neu[:24], len(roh), len(neu)))

        ldr = str(rec.leader)
        if ldr[9] != 'a':
            warnungen.append("Satz %d: Leader Pos. 09 = %r, erwartet 'a' (UTF-8)" % (n, ldr[9]))
        if ldr[20:24] != '4500':
            fehler.append("Satz %d: Entry Map = %r, erwartet '4500'" % (n, ldr[20:24]))

        for tag in ('001', '245'):
            if not rec.get_fields(tag):
                fehler.append("Satz %d: Pflichtfeld %s fehlt" % (n, tag))
        f008 = rec.get_fields('008')
        if f008 and len(f008[0].data) != 40:
            fehler.append("Satz %d: 008 hat %d statt 40 Zeichen" % (n, len(f008[0].data)))

    ergebnis['saetze'] = n
    if n == 0:
        fehler.append("Keine Saetze lesbar -- die Datei ist fuer MARC-Werkzeuge leer.")
    if erwartet is not None and n != erwartet:
        fehler.append("Satzzahl %d weicht von den erwarteten %d ab." % (n, erwartet))
    ergebnis['ok'] = not fehler
    return ergebnis


def _subfeld(rec, tag, code):
    """Erstes Subfeld oder Leerstring -- pymarc wirft sonst KeyError."""
    felder = rec.get_fields(tag)
    if not felder:
        return ''
    werte = felder[0].get_subfields(code)
    return werte[0] if werte else ''


def _steuerfeld(rec, tag):
    felder = rec.get_fields(tag)
    return felder[0].data if felder else ''


def _pl(n, singular, plural):
    """Zahl mit passender Singular-/Pluralform."""
    return "%d %s" % (n, singular if n == 1 else plural)


def check_content(data):
    """Inhaltliche Plausibilitaetspruefung -- unabhaengig von der MARC-Konformitaet.

    Eine Datei kann formal einwandfreies MARC21 sein und trotzdem fuer den
    Import unbrauchbare Daten enthalten. Geprueft wird deshalb zusaetzlich:
      * 001 fehlt, ist leer oder keine Zahl (z.B. der Platzhalter "UNKNOWN")
      * 001 kommt mehrfach vor
      * 035$a kommt mehrfach vor (mehrere Lokalsaetze zu einem Divibib-Titel)
      * 245$a fehlt, ist leer oder hat Leerzeichen am Rand

    Rueckgabe: {'warnungen': [str], 'hinweise': [str]}
    """
    ergebnis = {'warnungen': [], 'hinweise': []}
    try:
        from pymarc import MARCReader
    except ImportError:
        return ergebnis

    ids, quellen = [], []
    ohne_id, leere_titel, rand_titel = [], [], []
    n = 0
    for rec in MARCReader(io.BytesIO(data), to_unicode=True, force_utf8=True):
        if rec is None:
            continue
        n += 1
        satz_id = _steuerfeld(rec, '001').strip()
        ids.append(satz_id)
        if not satz_id or not satz_id.isdigit():
            ohne_id.append((n, satz_id or '(leer)'))
        quelle = _subfeld(rec, '035', 'a')
        if quelle:
            quellen.append(quelle)
        titel = _subfeld(rec, '245', 'a')
        if not titel.strip():
            leere_titel.append(n)
        elif titel != titel.strip():
            rand_titel.append(n)

    if ohne_id:
        beispiele = ", ".join("Satz %d = %r" % x for x in ohne_id[:5])
        ergebnis['warnungen'].append(
            "%s ohne verwertbare Satz-ID in Feld 001 (%s%s). Ein Loeschlauf, "
            "der ueber 001 identifiziert, kann diese Titel nicht zuordnen."
            % (_pl(len(ohne_id), "Satz", "Saetze"), beispiele,
               ", ..." if len(ohne_id) > 5 else ""))

    doppelte_ids = sorted(i for i, c in collections.Counter(ids).items()
                          if c > 1 and i.isdigit())
    if doppelte_ids:
        ergebnis['warnungen'].append(
            "%s in Feld 001: %s%s"
            % (_pl(len(doppelte_ids), "mehrfach vergebene Satz-ID",
                   "mehrfach vergebene Satz-IDs"),
               ", ".join(doppelte_ids[:5]),
               ", ..." if len(doppelte_ids) > 5 else ""))

    mehrfach = sorted(q for q, c in collections.Counter(quellen).items() if c > 1)
    if mehrfach:
        ergebnis['hinweise'].append(
            "%s (035$a) mit jeweils mehreren Lokalsaetzen unter unterschiedlicher "
            "001. Das ist kein Formatfehler, sollte aber bewusst so gewollt sein."
            % _pl(len(mehrfach), "Divibib-Kennung", "Divibib-Kennungen"))

    if leere_titel:
        ergebnis['warnungen'].append(
            "%s ohne Titel in 245$a (Satz %s)."
            % (_pl(len(leere_titel), "Satz", "Saetze"), leere_titel[:5]))
    if rand_titel:
        ergebnis['hinweise'].append(
            "%s in 245$a mit Leerzeichen am Anfang oder Ende."
            % _pl(len(rand_titel), "Titel", "Titel"))
    return ergebnis


def preview_records(data, limit=25):
    """Liefert eine Kurzvorschau (001/035/245) fuer die Anzeige."""
    try:
        from pymarc import MARCReader
    except ImportError:
        return []
    zeilen = []
    reader = MARCReader(io.BytesIO(data), to_unicode=True, force_utf8=True)
    for rec in reader:
        if rec is None:
            continue
        zeilen.append({
            'Satz-ID (001)': _steuerfeld(rec, '001'),
            'Titel (245$a)': _subfeld(rec, '245', 'a'),
            'Zusatz (245$b)': _subfeld(rec, '245', 'b'),
            'Quelle (035$a)': _subfeld(rec, '035', 'a'),
        })
        if len(zeilen) >= limit:
            break
    return zeilen


# --------------------------------------------------------------------------
# Kommandozeile
# --------------------------------------------------------------------------

def repair(src, dst):
    out, stat = repair_bytes(open(src, 'rb').read())
    open(dst, 'wb').write(out)
    print("Reparatur: %d Saetze gelesen, %d geschrieben, %d Bytes -> %s"
          % (stat['gelesen'], stat['geschrieben'], len(out), dst))
    for w in stat['warnungen']:
        print("  WARNUNG:", w)
    return stat['geschrieben']


def validate(path, erwartet=None):
    ergebnis = validate_bytes(open(path, 'rb').read(), erwartet)
    if not ergebnis['verfuegbar']:
        print("FEHLER: pymarc ist nicht installiert -- Pruefung nicht moeglich.")
        print("        Installation:  pip install pymarc")
        return False
    print("Pruefung (pymarc): %d Saetze gelesen aus %s" % (ergebnis['saetze'], path))
    for w in ergebnis['warnungen'][:20]:
        print("  WARNUNG:", w)
    if len(ergebnis['warnungen']) > 20:
        print("  ... %d weitere Warnungen" % (len(ergebnis['warnungen']) - 20))
    if ergebnis['fehler']:
        for f in ergebnis['fehler'][:20]:
            print("  FEHLER:", f)
        if len(ergebnis['fehler']) > 20:
            print("  ... %d weitere Fehler" % (len(ergebnis['fehler']) - 20))
        print("ERGEBNIS: NICHT konform (%d Fehler)" % len(ergebnis['fehler']))
        return False
    print("ERGEBNIS: gueltiges MARC21/ISO 2709 -- alle %d Saetze konform." % ergebnis['saetze'])

    inhalt = check_content(open(path, 'rb').read())
    if inhalt['warnungen'] or inhalt['hinweise']:
        print()
        print("Plausibilitaet (inhaltlich, kein Formatfehler):")
        for w in inhalt['warnungen']:
            print("  WARNUNG:", w)
        for h in inhalt['hinweise']:
            print("  HINWEIS:", h)
    return True


def main(argv):
    args = list(argv[1:])

    if '--pruefen' in args:
        args.remove('--pruefen')
        if len(args) != 1:
            print(__doc__)
            return 2
        return 0 if validate(args[0]) else 1

    pruefen = True
    if '--ohne-pruefung' in args:
        args.remove('--ohne-pruefung')
        pruefen = False
    if len(args) != 2:
        print(__doc__)
        return 2

    src, dst = args
    written = repair(src, dst)
    if not pruefen:
        return 0
    print()
    return 0 if validate(dst, erwartet=written) else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
