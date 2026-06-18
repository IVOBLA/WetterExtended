import json, os, sys
from pathlib import Path


def test_diagnose_motion_pipeline_offline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path/"train_data/objects").mkdir(parents=True)
    (tmp_path/"train_data/evaluation").mkdir(parents=True)
    objs = [{"id":"a","lat":46.0,"lon":14.0,"forecast_lat_10":46.0,"forecast_lon_10":14.0,
             "forecast_mode":"kinematic","kinematic_source":"kalman_only","of_available":0,
             "kinematic_speed_kmh":0.0,"kinematic_vx":0.0,"kinematic_vy":0.0}]
    (tmp_path/"train_data/objects/2099-01-01_00-00-00.json").write_text(json.dumps(objs), encoding="utf-8")
    (tmp_path/"train_data/evaluation/drift_status.json").write_text('{"drift_detected":true}', encoding="utf-8")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.diagnose_motion_pipeline import build_health
    health = build_health(24, tmp_path)
    assert health["of_available_pct"] == 0.0
    assert health["kinematic_source_counts"]["kalman_only"] == 1
    assert health["zero_forecast_pct_by_horizon"]["10"] == 100.0
    assert any("Optical Flow inactive" in d for d in health["diagnosis"])


def test_diagnose_motion_pipeline_has_no_network_imports():
    src = Path("tools/diagnose_motion_pipeline.py").read_text(encoding="utf-8")
    for token in ("requests", "httpx", "urllib", "urlopen", "http://", "https://"):
        assert token not in src
