import importlib
import sys
import types

import pytest


def _stub_heavy_modules(monkeypatch):
    np = types.SimpleNamespace(ndarray=object, float32=float)
    monkeypatch.setitem(sys.modules, "numpy", np)
    monkeypatch.setitem(sys.modules, "rasterio", types.SimpleNamespace(open=lambda *a, **k: None))
    monkeypatch.setitem(sys.modules, "rasterio.transform", types.SimpleNamespace(xy=lambda *a, **k: (0, 0)))
    monkeypatch.setitem(sys.modules, "scipy", types.SimpleNamespace(ndimage=types.SimpleNamespace(label=lambda mask: (mask, 0))))
    monkeypatch.setitem(sys.modules, "scipy.ndimage", types.SimpleNamespace(label=lambda mask: (mask, 0)))
    sys.modules.pop("ir_cell_detection", None)
    return importlib.import_module("ir_cell_detection")


def test_bt_230_default_height_about_9_8km(monkeypatch):
    mod = _stub_heavy_modules(monkeypatch)
    assert abs(mod._bt_to_height_m(230.0) - 9869.0) <= 50.0


def test_ir_stage_requires_convective_signal_for_public_watch(monkeypatch):
    mod = _stub_heavy_modules(monkeypatch)
    cell = {"cloud_height_m": 6600.0, "height_stage": "watch", "bt_min_k": 244.0, "area_px": 100}
    cell["ir_score"] = mod.calculate_ir_convective_score(cell)
    assert mod.classify_ir_stage(cell) == "inactive"
    cell["area_growth_px_per_min"] = 3.0
    cell["bt_trend_k_per_min"] = -0.2
    cell["ir_score"] = mod.calculate_ir_convective_score(cell)
    assert mod.classify_ir_stage(cell) == "ir_watch_candidate"


def test_ir_multistage_thresholds_with_growth_signal(monkeypatch):
    mod = _stub_heavy_modules(monkeypatch)
    base = {"bt_min_k": 229.0, "bt_trend_k_per_min": -0.2, "area_growth_px_per_min": 3.0, "cape": 300.0, "arome_li": -1.0}
    pre = dict(base, cloud_height_m=7600.0, height_stage="pre_cb", area_px=180)
    pre["ir_score"] = mod.calculate_ir_convective_score(pre)
    assert mod.classify_ir_stage(pre) == "ir_pre_cb"
    cb = dict(base, cloud_height_m=9200.0, height_stage="cb", area_px=320, overshooting_top=1.0)
    cb["ir_score"] = mod.calculate_ir_convective_score(cb)
    assert mod.classify_ir_stage(cb) == "ir_cb_precursor"
    severe = dict(cb, cloud_height_m=11100.0, height_stage="severe_cb", overshooting_top=0.0)
    severe["ir_score"] = mod.calculate_ir_convective_score(severe)
    assert severe["ir_score"] >= cb["ir_score"] - 0.1


def test_main_skip_path_runs_ir_pipeline_before_continue():
    text = open("main.py", encoding="utf-8").read()
    skip = text.index("if not radar_ok:")
    call = text.index("run_ir_precursor_pipeline(reason=f\"radar_skip", skip)
    cont = text.index("continue", skip)
    assert skip < call < cont


def test_pipeline_function_uses_fresh_tiff_guard_without_external_downloads():
    text = open("main.py", encoding="utf-8").read()
    start = text.index("def run_ir_precursor_pipeline")
    end = text.index("def _legacy_ir_radar_distance_match", start)
    body = text[start:end]
    assert "_latest_ir_tiff_fresh" in body
    assert "detect_ir_cells" in body and "update_ir_tracking" in body
    assert "download_kmz(" not in body and "requests.get" not in body
