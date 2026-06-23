"""B239 — Hydro-Legende ist aus der Karte entfernt."""

from pathlib import Path

MAPVIEW = Path(__file__).resolve().parent.parent / "frontend" / "src" / "pages" / "MapView.jsx"


def test_hydro_legend_absent():
    s = MAPVIEW.read_text(encoding="utf-8")
    for needle in ("Hydro-Pegel", "Hydro-Impact pending", "Hydro-Impact confirmed", "Hydro ambiguous"):
        assert needle not in s, f"Hydro-Legenden-Eintrag noch vorhanden: {needle}"
