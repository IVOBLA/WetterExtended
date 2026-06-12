"""
tests/test_b130_uncertainty_corridor.py

B130: MapView/MapFullscreen rendern einen q10/q90-Unsicherheitskorridor als ein
verbreiterndes Polygon (nur bei KI-Vorhersagen). Grep-basiert auf den JSX-Quellen;
der echte Build wird von tests/test_frontend_build.py geprueft.

Ausfuehrbar: python3 -m pytest tests/test_b130_uncertainty_corridor.py -v
"""
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    p = os.path.join(_ROOT, rel)
    assert os.path.exists(p), f"{rel} fehlt"
    with open(p, encoding="utf-8") as f:
        return f.read()


def _check(rel):
    txt = _read(rel)
    assert "B130: Unsicherheitskorridor" in txt
    assert "const _qpts = sorted.filter(s => s.q10 && s.q90)" in txt
    assert "const corridor = (!g.isKin && _qpts.length >= 1)" in txt
    assert "forecast_lat_q10" in txt and "forecast_lat_q90" in txt
    # Korridor nur bei KI (nicht kinematisch):
    assert "!g.isKin" in txt


def test_corridor_in_mapview():
    _check("frontend/src/pages/MapView.jsx")


def test_corridor_in_fullscreen():
    _check("frontend/src/pages/MapFullscreen.jsx")
