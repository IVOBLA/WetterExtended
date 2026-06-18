import json
import sys, types
sys.modules["debug_utils"] = types.SimpleNamespace(debug_log=lambda *a, **k: None)
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import accuracy_tracker
from accuracy_tracker import direction_error_deg, evaluate_all
from tools.diagnose_motion_pipeline import build_health
import debug_export
sys.modules.pop("debug_utils", None)


def _write_obj(path, objs):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(objs), encoding="utf-8")


def _setup(monkeypatch, tmp_path):
    obj = tmp_path / "objects"; ev = tmp_path / "evaluation"
    obj.mkdir(); ev.mkdir()
    monkeypatch.setitem(accuracy_tracker.SAVE_PATHS, "objects", str(obj))
    monkeypatch.setattr(accuracy_tracker, "EVAL_DIR", str(ev))
    monkeypatch.setattr(accuracy_tracker, "HISTORY_FILE", str(ev / "accuracy_history.jsonl"))
    monkeypatch.setattr(accuracy_tracker, "DETAILS_FILE", str(ev / "forecast_error_details.jsonl"))
    return obj, ev


def test_direction_error_wraparound():
    assert direction_error_deg(350, 10) == 20


def test_forecast_error_details_written(monkeypatch, tmp_path):
    obj_dir, ev = _setup(monkeypatch, tmp_path)
    _write_obj(obj_dir / "2026-01-01_00-00-00.json", [{"id":"a","lat":46.0,"lon":14.0,"forecast_lat_10":46.01,"forecast_lon_10":14.01,"forecast_x_10":10,"forecast_y_10":10,"forecast_mode":"ml","kinematic_source":"optflow_fm5.0","of_available":1}])
    _write_obj(obj_dir / "2026-01-01_00-10-00.json", [{"id":"a","lat":46.011,"lon":14.012,"x":3,"y":3}])
    res = evaluate_all([10], 24)
    accuracy_tracker.append_history_point(res)
    rows = [json.loads(l) for l in (ev / "forecast_error_details.jsonl").read_text().splitlines()]
    rec = rows[0]
    for k in ("forecast_mode","kinematic_source","forecast_error_km","forecast_speed_kmh","actual_speed_kmh","direction_error_deg","match_type"):
        assert k in rec
    assert rec["forecast_mode"] == "ml"
    assert rec["kinematic_source"] == "optflow_fm5.0"
    assert rec["match_type"] == "id"


def test_breakdowns_and_missing_target(monkeypatch, tmp_path):
    obj_dir, ev = _setup(monkeypatch, tmp_path)
    _write_obj(obj_dir / "2026-01-01_00-00-00.json", [
        {"id":"ml","lat":46.0,"lon":14.0,"forecast_lat_10":46.0,"forecast_lon_10":14.0,"forecast_x_10":0,"forecast_y_10":0,"forecast_mode":"ml","kinematic_source":"optflow_fm5.0"},
        {"id":"ki","lat":46.0,"lon":14.0,"forecast_lat_10":46.01,"forecast_lon_10":14.01,"forecast_x_10":0,"forecast_y_10":0,"forecast_mode":"kinematic","kinematic_source":"kalman_only"},
        {"id":"nt","lat":46.0,"lon":14.0,"forecast_lat_20":46.01,"forecast_lon_20":14.01,"forecast_x_20":0,"forecast_y_20":0,"forecast_mode":"kinematic","kinematic_source":"kalman_only"},
    ])
    _write_obj(obj_dir / "2026-01-01_00-10-00.json", [
        {"id":"ml","lat":46.02,"lon":14.02,"x":0,"y":0},
        {"id":"other","lat":46.0101,"lon":14.0101,"x":0,"y":0},
    ])
    res = evaluate_all([10,20], 24)
    assert res["breakdown_by_forecast_mode"]["10"]["ml"]["verified"] == 1
    assert res["breakdown_by_kinematic_source"]["10"]["kalman_only"]["verified"] == 1
    assert res["breakdown_by_match_type"]["10"]["nearest"]["verified"] == 1
    rows = [json.loads(l) for l in (ev / "forecast_error_details.jsonl").read_text().splitlines()]
    assert any(r["no_target_frame"] is True for r in rows)


def test_motion_pipeline_reads_accuracy_attribution(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ev = tmp_path / "train_data/evaluation"; obj = tmp_path / "train_data/objects"
    ev.mkdir(parents=True); obj.mkdir(parents=True)
    (ev / "forecast_error_details.jsonl").write_text('{"forecast_error_km": 1}\n', encoding="utf-8")
    (ev / "accuracy_history.jsonl").write_text(json.dumps({"timestamp_utc":"2026-01-01T00:00:00Z","breakdown_by_forecast_mode":{"10":{"ml":{"verified":1}}}})+"\n", encoding="utf-8")
    health = build_health(24, tmp_path)
    assert health["accuracy_attribution"]["breakdown_by_forecast_mode"]["10"]["ml"]["verified"] == 1


def test_debug_export_includes_forecast_error_details(tmp_path):
    ev = tmp_path / "train_data/evaluation"; ev.mkdir(parents=True)
    (ev / "forecast_error_details.jsonl").write_text('{"x":1}\n', encoding="utf-8")
    z, _, _ = debug_export.create_debug_export_zip(base_dir=tmp_path, tmp_path=tmp_path / "out.zip", now=datetime(2026,1,1,tzinfo=timezone.utc))
    with zipfile.ZipFile(z) as zf:
        assert any(n.endswith("forecast_error_details.jsonl") for n in zf.namelist())
