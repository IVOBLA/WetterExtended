"""B298: Health-/Alarmklassifikation für Radar-Ingest-Lücken."""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dataset_builder as db


def _touch_png(path, ts):
    p = path / f"{ts:%Y-%m-%d_%H-%M-%S}.png"
    p.write_bytes(b"\x89PNG\r\n")
    return p


def test_ok_status_when_no_gaps(monkeypatch, tmp_path):
    radar_dir = tmp_path / "radar"
    radar_dir.mkdir()
    eval_dir = tmp_path / "evaluation"
    monkeypatch.setitem(db.SAVE_PATHS, "radar", str(radar_dir))
    monkeypatch.setitem(db.SAVE_PATHS, "evaluation", str(eval_dir))

    now = datetime.utcnow().replace(second=0, microsecond=0)
    ts = now - timedelta(hours=1)
    while ts <= now:
        _touch_png(radar_dir, ts)
        ts += timedelta(minutes=5)

    result = db.compute_radar_ingest_gaps(5, hours=1)
    assert result["health_status"] == "ok"
    assert result["coverage_ratio"] >= 0.9


def test_critical_status_on_long_gap(monkeypatch, tmp_path):
    radar_dir = tmp_path / "radar"
    radar_dir.mkdir()
    eval_dir = tmp_path / "evaluation"
    monkeypatch.setitem(db.SAVE_PATHS, "radar", str(radar_dir))
    monkeypatch.setitem(db.SAVE_PATHS, "evaluation", str(eval_dir))

    now = datetime.utcnow().replace(second=0, microsecond=0)
    _touch_png(radar_dir, now - timedelta(minutes=55))
    _touch_png(radar_dir, now)  # 55-min Luecke = 11x expected_interval_min(5)

    result = db.compute_radar_ingest_gaps(5, hours=1)
    assert result["health_status"] == "critical"


def test_thresholds_runtime_overridable(monkeypatch, tmp_path):
    radar_dir = tmp_path / "radar"
    radar_dir.mkdir()
    eval_dir = tmp_path / "evaluation"
    monkeypatch.setitem(db.SAVE_PATHS, "radar", str(radar_dir))
    monkeypatch.setitem(db.SAVE_PATHS, "evaluation", str(eval_dir))

    now = datetime.utcnow().replace(second=0, microsecond=0)
    _touch_png(radar_dir, now - timedelta(minutes=15))
    _touch_png(radar_dir, now)  # 15-min Luecke = 3x expected_interval_min(5)

    class _Stub:
        @staticmethod
        def get(name, default=None):
            return {"RADAR_INGEST_GAP_WARN_FACTOR": 10.0, "RADAR_INGEST_GAP_CRITICAL_FACTOR": 20.0}.get(name, default)

    monkeypatch.setattr(db, "_rc", _Stub())
    result = db.compute_radar_ingest_gaps(5, hours=1)
    assert result["health_status"] == "ok"
