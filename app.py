#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 André Wendler
"""
Streamlit-Oberflaeche fuer die Reparatur kaputter Divibib-MARC21-Exporte.

Ablauf: Datei hochladen -> Diagnose -> Reparatur -> Pruefung mit pymarc -> Download.

Datenschutz / Persistenz:
Die App speichert nichts. Die hochgeladene Datei wird ausschliesslich im
Arbeitsspeicher des Serverprozesses verarbeitet, es wird weder auf die Platte
geschrieben noch gecacht (bewusst kein st.cache_data auf Dateiinhalte) noch in
st.session_state abgelegt. Nach dem Rerun bzw. dem Schliessen des Browsertabs
ist der Inhalt weg.
"""
import streamlit as st

import fix_marc

st.set_page_config(page_title="Divibib-MARC-Reparatur", page_icon="📚", layout="wide")

st.title("📚 Divibib-MARC-Reparatur")
st.caption(
    "Repariert fehlerhafte ISO-2709-/MARC21-Exporte, prueft das Ergebnis mit pymarc "
    "und bietet die korrigierte Datei zum Download an."
)

with st.sidebar:
    st.header("Hinweise")
    st.info(
        "**Es werden keine Daten gespeichert.**\n\n"
        "Die Verarbeitung findet ausschliesslich im Arbeitsspeicher statt: "
        "kein Schreiben auf die Platte, kein Cache, keine Session-Ablage. "
        "Mit dem Schliessen des Browsertabs ist alles weg."
    )
    st.markdown(
        "**Was repariert wird**\n"
        "1. Fehlendes Directory (Tags standen inline)\n"
        "2. Leader Pos. 08/09 vertauscht\n"
        "3. Entry Map `450 ` statt `4500`\n"
        "4. Falsche Satzlaenge und Base Address\n"
        "5. Doppelte Record Terminatoren (`0x1D`)\n"
        "6. Fehlender Field Terminator am Satzende\n"
        "7. Feld `008` mit 41 statt 40 Zeichen\n"
        "8. Datenfelder mit nur einem Indikator\n"
        "9. Datei-Terminator `0x1C` am Dateiende"
    )
    vorschau_an = st.checkbox("Satzvorschau anzeigen", value=True)

hochgeladen = st.file_uploader(
    "MARC-Dateien auswaehlen",
    type=["mrc", "marc", "dat", "mrk", "iso", "bin"],
    accept_multiple_files=True,
    help="Mehrere Dateien gleichzeitig moeglich. Der Inhalt verlaesst den Arbeitsspeicher nicht.",
)

if not hochgeladen:
    st.info("Lade eine oder mehrere MARC-Dateien hoch, um zu beginnen.")
    st.stop()

if not fix_marc.validate_bytes(b"")['verfuegbar']:
    st.error("pymarc ist nicht installiert – die Pruefung ist nicht moeglich. "
             "Bitte `pip install pymarc` ausfuehren.")
    st.stop()


def zeige_liste(titel, eintraege, art, maximal=25):
    """Klappt eine Fehler- oder Warnungsliste auf."""
    if not eintraege:
        return
    with st.expander("%s (%d)" % (titel, len(eintraege)), expanded=(art == "error")):
        for e in eintraege[:maximal]:
            st.markdown("- `%s`" % e)
        if len(eintraege) > maximal:
            st.caption("... %d weitere" % (len(eintraege) - maximal))


for datei in hochgeladen:
    st.divider()
    st.subheader(datei.name)

    # getvalue() liefert den vollstaendigen Inhalt unabhaengig von der
    # Lesposition -- wichtig, weil Streamlit bei jedem Klick neu rendert.
    roh = datei.getvalue()

    befund = fix_marc.analyse(roh)

    # ---------------------------------------------------------------- Diagnose
    st.markdown("**1. Diagnose**")
    if befund['bereits_gueltig']:
        st.success(
            "Diese Datei ist bereits gueltiges MARC21/ISO 2709 (%d Saetze). "
            "Eine Reparatur ist nicht noetig und wird deshalb nicht angeboten."
            % befund['saetze']
        )
        if vorschau_an:
            zeilen = fix_marc.preview_records(roh)
            if zeilen:
                st.dataframe(zeilen, use_container_width=True, hide_index=True)
        continue

    if befund['defekte']:
        for d in befund['defekte']:
            st.markdown("- %s" % d)
    else:
        st.markdown("- Keine bekannten Defektmuster erkannt.")

    if not befund['reparierbar']:
        st.error(
            "Die Datei ist nicht lesbar, entspricht aber **nicht** dem bekannten "
            "Divibib-Defektmuster (fehlendes Directory bei inline stehenden Feldtags). "
            "Eine automatische Reparatur waere Raterei und wird deshalb nicht ausgefuehrt."
        )
        continue

    # -------------------------------------------------------------- Reparatur
    st.markdown("**2. Reparatur**")
    neu, stat = fix_marc.repair_bytes(roh)

    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Saetze gelesen", stat['gelesen'])
    s2.metric("Saetze geschrieben", stat['geschrieben'],
              delta=stat['geschrieben'] - stat['gelesen'] or None)
    s3.metric("Groesse vorher", "%.1f kB" % (len(roh) / 1024))
    s4.metric("Groesse nachher", "%.1f kB" % (len(neu) / 1024))
    zeige_liste("Warnungen aus der Reparatur", stat['warnungen'], "warning")

    # -------------------------------------------------------------- Pruefung
    st.markdown("**3. Pruefung mit pymarc**")
    ergebnis = fix_marc.validate_bytes(neu, erwartet=stat['geschrieben'])

    if ergebnis['ok']:
        st.success(
            "Gueltiges MARC21/ISO 2709 – alle %d Saetze konform. "
            "Geprueft wurden: Dekodierbarkeit, byte-genauer Roundtrip ueber "
            "`Record.as_marc()`, Leader Pos. 09/20-23, Pflichtfelder 001 und 245, "
            "Laenge von Feld 008 und die Satzzahl." % ergebnis['saetze']
        )
    else:
        st.error("Die reparierte Datei ist **nicht** konform (%d Fehler). "
                 "Der Download ist trotzdem moeglich, sollte aber nicht importiert werden."
                 % len(ergebnis['fehler']))
    zeige_liste("Fehler", ergebnis['fehler'], "error")
    zeige_liste("Warnungen", ergebnis['warnungen'], "warning")

    # -------------------------------------------------- Plausibilitaet
    st.markdown("**4. Plausibilitaet (inhaltlich)**")
    inhalt = fix_marc.check_content(neu)
    if inhalt['warnungen'] or inhalt['hinweise']:
        st.caption("Keine Formatfehler – die Datei bleibt gueltiges MARC21. "
                   "Diese Punkte koennen den Import aber trotzdem stoeren.")
        for w in inhalt['warnungen']:
            st.warning(w)
        for h in inhalt['hinweise']:
            st.info(h)
    else:
        st.success("Satz-IDs und Titel sind vollstaendig und eindeutig.")

    # -------------------------------------------------------------- Vorschau
    if vorschau_an and ergebnis['saetze']:
        zeilen = fix_marc.preview_records(neu)
        if zeilen:
            st.markdown("**5. Vorschau (erste %d Saetze)**" % len(zeilen))
            st.dataframe(zeilen, use_container_width=True, hide_index=True)

    # -------------------------------------------------------------- Download
    name = datei.name.rsplit('.', 1)[0] + "_fixed.mrc"
    st.download_button(
        "⬇ %s herunterladen" % name,
        data=neu,
        file_name=name,
        mime="application/marc",
        type="primary" if ergebnis['ok'] else "secondary",
        key="dl_" + datei.name,
    )
