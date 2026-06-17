"""B176: Horizont-wachsender Unsicherheitskegel (Fallback ohne Quantile) im Frontend."""
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FILES = (
    "frontend/src/pages/MapView.jsx",
    "frontend/src/pages/MapFullscreen.jsx",
)


def _read(rel):
    with open(os.path.join(_ROOT, rel), encoding="utf-8") as f:
        return f.read()


def test_cone_computed_in_both_files():
    for rel in _FILES:
        src = _read(rel)
        assert "B176" in src, f"B176-Marker fehlt in {rel}"
        assert "const cone = corridor ? null" in src, f"Kegel-Berechnung fehlt in {rel}"
        assert "CONE_GROWTH_KM_PER_MIN" in src, f"Wachstumsrate fehlt in {rel}"


def test_cone_rendered_in_both_files():
    for rel in _FILES:
        src = _read(rel)
        assert "{cone && (" in src, f"Kegel-Render fehlt in {rel}"


def test_corridor_still_present():
    # B130-Korridor darf nicht entfernt worden sein.
    for rel in _FILES:
        assert "const corridor = (!g.isKin && _qpts.length >= 1)" in _read(rel)
