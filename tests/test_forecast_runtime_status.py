import json
from pathlib import Path

import pytest


def _patch_paths(monkeypatch, tmp_path):
    import config, ml_readiness
    sp = dict(config.SAVE_PATHS)
    sp.update({
        "models": str(tmp_path / "models"),
        "evaluation": str(tmp_path / "evaluation"),
        "dataset": str(tmp_path / "dataset"),
    })
    monkeypatch.setattr(config, "SAVE_PATHS", sp, raising=False)
    monkeypatch.setattr(ml_readiness, "SAVE_PATHS", sp, raising=False)
    monkeypatch.setattr(ml_readiness, "ML_NUM_FEATURES", 1, raising=False)
    monkeypatch.setattr(ml_readiness, "_runtime_horizons", lambda: [10, 20], raising=False)
    return sp


def _valid_current(root, horizons=(10, 20)):
    cur = Path(root) / "models" / "current"
    cur.mkdir(parents=True)
    (cur / "scaler_X.joblib").write_text("x")
    (cur / "scaler_y.joblib").write_text("y")
    for h in horizons:
        (cur / f"lgbm_h{h}_x.txt").write_text("m")
        (cur / f"lgbm_h{h}_y.txt").write_text("m")
    return cur


def test_runtime_status_current_valid_all_horizons(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    _valid_current(tmp_path)
    import ml_readiness
    class Joblib:
        @staticmethod
        def load(path):
            n = 4 if str(path).endswith("scaler_y.joblib") else 1
            return type("Scaler", (), {"n_features_in_": n})()
    class Booster:
        def __init__(self, model_file): pass
        def num_feature(self): return 1
    monkeypatch.setattr(ml_readiness, "_opt", lambda name: Joblib if name == "joblib" else type("LGB", (), {"Booster": Booster}) if name == "lightgbm" else None)
    st = ml_readiness.get_forecast_runtime_status(write_json=False)
    assert st["runtime_mode"] == "ml"
    assert st["fallback_reason"] is None
    assert st["missing_horizons"] == []


def test_runtime_status_current_missing(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    import ml_readiness
    st = ml_readiness.get_forecast_runtime_status(write_json=False)
    assert st["runtime_mode"] == "kinematic_fallback"
    assert st["fallback_reason"]


def test_runtime_status_partial_horizons(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    _valid_current(tmp_path, horizons=(10,))
    import ml_readiness
    class Joblib:
        @staticmethod
        def load(path):
            n = 4 if str(path).endswith("scaler_y.joblib") else 1
            return type("Scaler", (), {"n_features_in_": n})()
    class Booster:
        def __init__(self, model_file): pass
        def num_feature(self): return 1
    monkeypatch.setattr(ml_readiness, "_opt", lambda name: Joblib if name == "joblib" else type("LGB", (), {"Booster": Booster}) if name == "lightgbm" else None)
    st = ml_readiness.get_forecast_runtime_status(write_json=False)
    assert st["runtime_mode"] == "ml"
    assert st["missing_horizons"] == [20]
    assert st["forecast_mode_by_horizon"]["20"] == "kinematic_fallback"


def test_dashboard_stats_separate_runtime_and_history(monkeypatch, tmp_path):
    pytest.importorskip("flask")
    import app
    obj_dir = tmp_path / "objects"; obj_dir.mkdir()
    (obj_dir / "2026-06-19_00-00-00.json").write_text(json.dumps([{"forecast_mode":"kinematic_fallback"}]))
    monkeypatch.setitem(app.SAVE_PATHS, "objects", str(obj_dir))
    monkeypatch.setattr(app, "datetime", type("D", (), {"utcnow": staticmethod(lambda: __import__('datetime').datetime(2026,6,19,1,0,0))}))
    monkeypatch.setattr("ml_readiness.get_forecast_runtime_status", lambda write_json=False: {"runtime_mode":"ml","fallback_reason":None,"active_horizons":[10,20],"ml_model_version":"v_x"})
    c = app.app.test_client()
    data = c.get("/api/forecast_stats?hours=24").get_json()
    assert data["current_runtime_mode"] == "ml"
    assert data["historical_24h_usage"]["fallback_pct"] == 100.0
