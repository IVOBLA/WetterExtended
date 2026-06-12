"""
tests/test_optflow_area_mean.py

P-M01: of_vx/of_vy werden über das Zellpolygon flächengemittelt (nicht am
Schwerpunkt punktabgetastet) und ignorieren NaN-Flow-Pixel. of_available
spiegelt echte Verfügbarkeit wider.

Ausführbar: python3 -m pytest tests/test_optflow_area_mean.py -v
"""
import os
import sys
import types
import importlib

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _install_fake_pysteps(uv):
    """Stellt pysteps.motion.lucaskanade.dense_lucaskanade als Fake bereit,
    der ein vorgegebenes UV-Feld (2,H,W) zurückgibt — unabhängig davon, ob
    pysteps real installiert ist."""
    mod_ps = sys.modules.get("pysteps") or types.ModuleType("pysteps")
    mod_motion = sys.modules.get("pysteps.motion") or types.ModuleType("pysteps.motion")
    mod_lk = types.ModuleType("pysteps.motion.lucaskanade")
    mod_lk.dense_lucaskanade = lambda stack, **kw: uv
    mod_ps.motion = mod_motion
    mod_motion.lucaskanade = mod_lk
    sys.modules["pysteps"] = mod_ps
    sys.modules["pysteps.motion"] = mod_motion
    sys.modules["pysteps.motion.lucaskanade"] = mod_lk


def _prepare(monkeypatch, tmp_path, uv):
    of = importlib.import_module("optical_flow_features")
    _install_fake_pysteps(uv)
    monkeypatch.setattr(of, "_pysteps_ok", True, raising=False)
    monkeypatch.setattr(of, "_np_ok", True, raising=False)
    # _load_gray darf nicht None liefern (Inhalt egal, UV ist gefaket)
    h, w = uv.shape[1], uv.shape[2]
    monkeypatch.setattr(of, "_load_gray", lambda p: np.ones((h, w), dtype="float32"))
    prev = tmp_path / "prev.png"
    curr = tmp_path / "curr.png"
    prev.write_bytes(b"x")
    curr.write_bytes(b"x")
    return of, str(prev), str(curr)


def test_area_mean_ignores_nan_pixels(monkeypatch, tmp_path):
    """U[y,x] = x für x<6, NaN für x>=6 (simuliert Merge-Lücke).
    Polygon spannt Spalten 3..8 → gültige Spalten 3,4,5 → Mittel U = 4.0.
    of_vx erwartet = 4.0 / UPSCALE_FACTOR."""
    from config import UPSCALE_FACTOR
    H = W = 30
    U = np.empty((H, W), dtype="float32")
    for x in range(W):
        U[:, x] = float(x) if x < 6 else np.nan
    V = np.zeros((H, W), dtype="float32")
    uv = np.stack([U, V], axis=0)

    of, prev, curr = _prepare(monkeypatch, tmp_path, uv)

    obj = {
        "id": "merge_gap",
        "x": 5.5 / UPSCALE_FACTOR, "y": 5.5 / UPSCALE_FACTOR,
        "contour": [[3, 3], [8, 3], [8, 8], [3, 8]],
    }
    out = of.assign_optical_flow_to_objects([obj], prev, curr)[0]

    assert out["of_available"] == 1, "Gültige Pixel im Polygon → of_available=1"
    expected_vx = 4.0 / UPSCALE_FACTOR
    assert abs(out["of_vx"] - expected_vx) < 0.05, (
        f"of_vx muss Flächenmittel (≈{expected_vx:.3f}) sein, war {out['of_vx']}. "
        f"NaN-Pixel der Merge-Lücke dürfen nicht einfließen."
    )
    assert abs(out["of_vy"]) < 1e-6


def test_all_nan_polygon_marks_unavailable(monkeypatch, tmp_path):
    """Polygon vollständig im NaN-Bereich UND Zentrum NaN → of_available=0."""
    from config import UPSCALE_FACTOR
    H = W = 30
    U = np.full((H, W), np.nan, dtype="float32")
    V = np.full((H, W), np.nan, dtype="float32")
    uv = np.stack([U, V], axis=0)

    of, prev, curr = _prepare(monkeypatch, tmp_path, uv)

    obj = {
        "id": "all_nan",
        "x": 12.0 / UPSCALE_FACTOR, "y": 12.0 / UPSCALE_FACTOR,
        "contour": [[9, 9], [15, 9], [15, 15], [9, 15]],
    }
    out = of.assign_optical_flow_to_objects([obj], prev, curr)[0]

    assert out["of_available"] == 0, "Kein gültiger Flow → of_available=0"
    assert out["of_vx"] == 0.0 and out["of_vy"] == 0.0


def test_uniform_field_matches_value(monkeypatch, tmp_path):
    """Homogenes Feld U=2, V=-1 → Flächenmittel = exakt der Feldwert."""
    from config import UPSCALE_FACTOR
    H = W = 20
    U = np.full((H, W), 2.0, dtype="float32")
    V = np.full((H, W), -1.0, dtype="float32")
    uv = np.stack([U, V], axis=0)

    of, prev, curr = _prepare(monkeypatch, tmp_path, uv)

    obj = {
        "id": "uniform",
        "x": 8.0 / UPSCALE_FACTOR, "y": 8.0 / UPSCALE_FACTOR,
        "contour": [[5, 5], [11, 5], [11, 11], [5, 11]],
    }
    out = of.assign_optical_flow_to_objects([obj], prev, curr)[0]

    assert out["of_available"] == 1
    assert abs(out["of_vx"] - 2.0 / UPSCALE_FACTOR) < 1e-4
    assert abs(out["of_vy"] - (-1.0 / UPSCALE_FACTOR)) < 1e-4
