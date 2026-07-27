"""
tests/test_b478_corridor_crosstrack.py

B478: Der q10/q90-Unsicherheitskorridor (B130) wird per QUERprojektion der
achsenparallelen Box gebaut (Stützfunktion r = |px|*hx + |py|*hy) und um den
Zentralpunkt seitlich versetzt — NICHT mehr durch direktes Verbinden der zwei
Box-Diagonalecken. Grep-basiert auf den JSX-Quellen; der echte Build wird von
tests/test_frontend_build.py geprueft.

Ausfuehrbar: python3 -m pytest tests/test_b478_corridor_crosstrack.py -v
"""
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FILES = ["frontend/src/pages/MapView.jsx", "frontend/src/pages/MapFullscreen.jsx"]

_OLD_RAIL = "..._qpts.map(s => s.q10), ..._qpts.slice().reverse().map(s => s.q90)]"
_SUPPORT = "const r = Math.abs(px) * hx + Math.abs(py) * hy"


def _read(rel):
    p = os.path.join(_ROOT, rel)
    assert os.path.exists(p), f"{rel} fehlt"
    with open(p, encoding="utf-8") as f:
        return f.read()


def _check(rel):
    txt = _read(rel)
    # B130-Kern-Anker bleiben erhalten (Rueckwaertskompatibilitaet):
    assert "B130: Unsicherheitskorridor" in txt
    assert "const _qpts = sorted.filter(s => s.q10 && s.q90)" in txt
    assert "const corridor = (!g.isKin && _qpts.length >= 1)" in txt
    # B478-Marker + korrekte Querprojektion vorhanden:
    assert "B478" in txt, f"B478-Marker fehlt in {rel}"
    assert _SUPPORT in txt, f"Stuetzfunktion fehlt in {rel}"
    # Kommentar-Marker eindeutig B478 (nicht der B176-Kegel, der 'Perpendikular' heisst):
    assert "// Quer-Einheitsvektor (km-Frame)" in txt, f"Quer-Achse (B478) fehlt in {rel}"
    # Alte diagonale Schienen-Konstruktion ist ENTFERNT:
    assert _OLD_RAIL not in txt, f"Alte Box-Diagonalkonstruktion noch vorhanden in {rel}"


def test_corridor_crosstrack_mapview():
    _check("frontend/src/pages/MapView.jsx")


def test_corridor_crosstrack_fullscreen():
    _check("frontend/src/pages/MapFullscreen.jsx")
