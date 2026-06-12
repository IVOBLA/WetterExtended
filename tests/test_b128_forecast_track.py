"""
tests/test_b128_forecast_track.py

B128: MapView/MapFullscreen rendern eine durchgehende Zugbahn statt radialer
Einzelpfeile. Grep-basiert auf den JSX-Quellen (der echte Build wird von
tests/test_frontend_build.py geprueft).

Ausfuehrbar: python3 -m pytest tests/test_b128_forecast_track.py -v
"""
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    p = os.path.join(_ROOT, rel)
    assert os.path.exists(p), f"{rel} fehlt"
    with open(p, encoding="utf-8") as f:
        return f.read()


def test_track_block_present_in_mapview():
    txt = _read("frontend/src/pages/MapView.jsx")
    assert "B128: Durchgehende Zugbahn" in txt
    assert "'track_' +" in txt
    # alter radialer Block ist entfernt:
    assert "{/* Vorhersage-Pfeile nur beim neuesten Frame */}" not in txt


def test_track_block_present_in_fullscreen():
    txt = _read("frontend/src/pages/MapFullscreen.jsx")
    assert "B128: Durchgehende Zugbahn" in txt
    assert "'track_' +" in txt


def test_uses_forecast_features_grouping():
    for rel in ("frontend/src/pages/MapView.jsx",
                "frontend/src/pages/MapFullscreen.jsx"):
        txt = _read(rel)
        assert "forecast.features" in txt
        assert "p.forecast_mode !== 'kinematic'" in txt
