"""B295: Lineare Interpolation der Ziel-Objektposition zwischen zwei realen
Radarframes, wenn kein Frame direkt innerhalb der adaptiven Toleranz liegt."""
import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from accuracy_tracker import _interpolate_target_objects


def _write_objs(path, objs):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(objs, f)


def test_interpolates_matching_ids(tmp_path):
    t0 = datetime(2026, 7, 3, 17, 0, 0)
    t1 = datetime(2026, 7, 3, 17, 20, 0)  # 20-min Luecke, wie im Debug-Export
    p0 = tmp_path / "f0.json"
    p1 = tmp_path / "f1.json"
    _write_objs(p0, [{"id": "WX-1", "lat": 46.70, "lon": 15.00}])
    _write_objs(p1, [{"id": "WX-1", "lat": 46.72, "lon": 15.02}])
    by_ts = {t0: str(p0), t1: str(p1)}
    target_ts = t0 + timedelta(minutes=10)  # exakt in der Mitte

    result = _interpolate_target_objects(by_ts, target_ts, max_gap_s=1800)

    assert result is not None
    assert len(result) == 1
    assert result[0]["id"] == "WX-1"
    assert abs(result[0]["lat"] - 46.71) < 1e-9
    assert abs(result[0]["lon"] - 15.01) < 1e-9
    assert result[0]["_interpolated_target"] is True


def test_returns_none_if_gap_too_large(tmp_path):
    t0 = datetime(2026, 7, 3, 17, 0, 0)
    t1 = datetime(2026, 7, 3, 18, 0, 0)  # 60-min Luecke > max_gap_s
    p0 = tmp_path / "f0.json"
    p1 = tmp_path / "f1.json"
    _write_objs(p0, [{"id": "WX-1", "lat": 46.70, "lon": 15.00}])
    _write_objs(p1, [{"id": "WX-1", "lat": 46.72, "lon": 15.02}])
    by_ts = {t0: str(p0), t1: str(p1)}
    target_ts = t0 + timedelta(minutes=30)

    assert _interpolate_target_objects(by_ts, target_ts, max_gap_s=1800) is None


def test_returns_none_if_ids_dont_match(tmp_path):
    t0 = datetime(2026, 7, 3, 17, 0, 0)
    t1 = datetime(2026, 7, 3, 17, 20, 0)
    p0 = tmp_path / "f0.json"
    p1 = tmp_path / "f1.json"
    _write_objs(p0, [{"id": "WX-1", "lat": 46.70, "lon": 15.00}])
    _write_objs(p1, [{"id": "WX-2", "lat": 46.72, "lon": 15.02}])
    by_ts = {t0: str(p0), t1: str(p1)}
    target_ts = t0 + timedelta(minutes=10)

    assert _interpolate_target_objects(by_ts, target_ts, max_gap_s=1800) is None


def test_returns_none_without_two_bracketing_frames():
    t0 = datetime(2026, 7, 3, 17, 0, 0)
    by_ts = {t0: "irrelevant.json"}
    target_ts = t0 + timedelta(minutes=10)
    assert _interpolate_target_objects(by_ts, target_ts, max_gap_s=1800) is None
