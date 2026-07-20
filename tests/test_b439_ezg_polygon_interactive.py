"""B439: EZG-Polygon darf keine Klicks abfangen; loadCatchment lädt nur einmalig.

Symptom 2026-07-20: sobald das Einzugsgebiet einer Station eingeblendet war, ging bei
keiner Station mehr ein Popup auf. Ursache: das Polygon war interaktiv (Leaflet-Default)
und deckte die Marker ab; zusätzlich lud der Klick-Handler das EZG bei jedem Klick neu
und schloss durch das Re-Render das gerade geöffnete Popup.
"""
import re
from pathlib import Path

import pytest

FILES = ["frontend/src/pages/MapView.jsx", "frontend/src/pages/MapFullscreen.jsx"]


@pytest.mark.parametrize("path", FILES)
def test_ezg_polygon_ist_nicht_interaktiv(path):
    t = Path(path).read_text(encoding="utf-8")
    m = re.search(r"hydro_catch_\$\{p\.station_id\}_\$\{i\}[^\n]*", t)
    assert m, f"EZG-Polygon-Zeile nicht gefunden in {path}"
    line = m.group(0)
    assert "interactive: false" in line, (
        f"EZG-Polygon in {path} ist noch interaktiv — es fängt Klicks ab und "
        "blockiert die Stations-Popups."
    )


@pytest.mark.parametrize("path", FILES)
def test_loadcatchment_laedt_nur_einmalig(path):
    t = Path(path).read_text(encoding="utf-8")
    # Der Guard 'if (prev[p.station_id]) return prev' muss vorhanden sein.
    assert "if (prev[p.station_id]) return prev" in t, (
        f"loadCatchment in {path} lädt weiterhin bei jedem Klick neu — "
        "das Re-Render schließt das gerade geöffnete Popup."
    )


@pytest.mark.parametrize("path", FILES)
def test_kein_doppeltes_setstate_ohne_guard(path):
    """Der ursprüngliche, ungeschützte Einzeiler darf nicht mehr existieren."""
    t = Path(path).read_text(encoding="utf-8")
    bad = ".then(d => setHydroCatchments(prev => ({ ...prev, [p.station_id]: hydroFeatureCollection(d) })))"
    # Erlaubt ist nur noch die geschachtelte Form mit 'cur'; die alte 'prev'-Form
    # direkt im .then ist der ungeschützte Pfad.
    assert bad not in t, f"Ungeschützter loadCatchment-Pfad noch vorhanden in {path}"
