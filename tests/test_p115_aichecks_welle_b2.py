"""P115 — Welle B (Teil 2): AC-068 und AC-076 deterministisch migriert.

Beide teilen dieselbe Geometrie-Grundlage (forecast_lat_<h>/lon_<h>-Kette,
Horizonte 10/20/30/40/60) und werden deshalb hier gemeinsam getestet.
"""
import json
from pathlib import Path

from tools.ai_checks.checks_local import (
    check_ac076_bearing_jumps_mixed_mode as ac076,
    check_ac068_speed_and_zigzag_plausibility as ac068,
    _bearing_deg,
    _bearing_change_deg,
)

_HORIZONS = (10, 20, 30, 40, 60)


def _frame_dir(tmp_path):
    d = tmp_path / "objects" / "train_data" / "objects"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _base_obj(**overrides):
    obj = {
        "cell_id": "1", "lat": 46.60, "lon": 14.30, "speed_kmh": 30,
        "history": [{"timestamp": "2026-08-05_07-35-00"},
                    {"timestamp": "2026-08-05_07-40-00"}],
    }
    for h in _HORIZONS:
        obj[f"forecast_lat_{h}"] = 46.60 + 0.01 * (h / 10)
        obj[f"forecast_lon_{h}"] = 14.30
        obj[f"forecast_mode_{h}"] = "ml"
    obj.update(overrides)
    return obj


def _write_frame(tmp_path, ts, objs):
    (_frame_dir(tmp_path) / f"{ts}.json").write_text(json.dumps(objs), encoding="utf-8")


def test_bearing_deg_north_is_zero():
    assert round(_bearing_deg(46.6, 14.3, 46.7, 14.3), 0) == 0


def test_bearing_deg_east_is_90():
    assert round(_bearing_deg(46.6, 14.3, 46.6, 14.4), 0) == 90


def test_bearing_change_handles_wraparound():
    assert _bearing_change_deg(10, 350) == 20
    assert _bearing_change_deg(10, 200) == 170


def test_ac076_ok_no_frames(tmp_path):
    r = ac076(tmp_path)
    assert r["status"] == "ok"
    assert r["detail"]["mixed_case_count"] == 0


def test_ac076_ok_straight_line_mixed_modes(tmp_path):
    obj = _base_obj(forecast_mode_30="kinematic_fallback", forecast_mode_40="kinematic_fallback",
                    forecast_mode_60="kinematic_fallback")
    _write_frame(tmp_path, "2026-08-05_07-40-00", [obj])
    r = ac076(tmp_path)
    assert r["status"] == "ok"
    assert r["detail"]["mixed_case_count"] == 1


def test_ac076_ok_zigzag_but_pure_mode(tmp_path):
    obj = _base_obj(forecast_lat_40=46.61, forecast_lon_40=14.30,
                    forecast_lat_60=46.61, forecast_lon_60=14.45)
    _write_frame(tmp_path, "2026-08-05_07-45-00", [obj])
    r = ac076(tmp_path)
    assert r["status"] == "ok"
    assert r["detail"]["mixed_case_count"] == 0


def test_ac076_finding_zigzag_mixed_mode(tmp_path):
    obj = _base_obj(forecast_lat_40=46.61, forecast_lon_40=14.30,
                    forecast_lat_60=46.61, forecast_lon_60=14.45,
                    forecast_mode_30="kinematic_fallback", forecast_mode_40="kinematic_fallback",
                    forecast_mode_60="kinematic_fallback")
    _write_frame(tmp_path, "2026-08-05_07-50-00", [obj])
    r = ac076(tmp_path)
    assert r["status"] == "finding"
    assert r["detail"]["findings"]
    assert r["detail"]["findings"][0]["cell_id"] == "1"


def test_ac076_reports_consistency_adjusted_quote(tmp_path):
    obj = _base_obj(forecast_lat_40=46.61, forecast_lon_40=14.30,
                    forecast_lat_60=46.61, forecast_lon_60=14.45,
                    forecast_mode_30="kinematic_fallback", forecast_mode_40="kinematic_fallback",
                    forecast_mode_60="kinematic_fallback",
                    forecast_consistency_adjusted_60=True)
    _write_frame(tmp_path, "2026-08-05_07-55-00", [obj])
    r = ac076(tmp_path)
    assert r["status"] == "finding"
    assert r["detail"]["adjusted_quote"] == 1.0


def test_ac076_ignores_incomplete_forecast_chain(tmp_path):
    obj = _base_obj(forecast_mode_30="kinematic_fallback")
    del obj["forecast_lat_60"]
    _write_frame(tmp_path, "2026-08-05_08-00-00", [obj])
    r = ac076(tmp_path)
    assert r["status"] == "ok"


def test_ac068_ok_no_frames(tmp_path):
    r = ac068(tmp_path)
    assert r["status"] == "ok"


def test_ac068_ok_normal_speed_straight_line(tmp_path):
    _write_frame(tmp_path, "2026-08-05_07-40-00", [_base_obj()])
    r = ac068(tmp_path)
    assert r["status"] == "ok"


def test_ac068_finding_overspeed_with_short_dt_hypothesis(tmp_path):
    obj = _base_obj(speed_kmh=90, history=[{"timestamp": "2026-08-05_07-38-00"},
                                            {"timestamp": "2026-08-05_07-40-00"}])
    _write_frame(tmp_path, "2026-08-05_07-45-00", [obj])
    r = ac068(tmp_path)
    assert r["status"] == "finding"
    assert "Hypothese" in r["beleg"]
    assert r["detail"]["overspeed"][0]["real_dt_min"] == 2.0


def test_ac068_finding_overspeed_normal_dt_no_hypothesis(tmp_path):
    obj = _base_obj(speed_kmh=90, history=[{"timestamp": "2026-08-05_07-30-00"},
                                            {"timestamp": "2026-08-05_07-40-00"}])
    _write_frame(tmp_path, "2026-08-05_07-45-00", [obj])
    r = ac068(tmp_path)
    assert r["status"] == "finding"
    assert "Hypothese" not in r["beleg"]


def test_ac068_finding_zigzag_without_mode_restriction(tmp_path):
    obj = _base_obj(forecast_lat_40=46.61, forecast_lon_40=14.30,
                    forecast_lat_60=46.61, forecast_lon_60=14.45)
    _write_frame(tmp_path, "2026-08-05_07-50-00", [obj])
    r = ac068(tmp_path)
    assert r["status"] == "finding"
    assert "eigenstaendiges Prognose-Problem" in r["beleg"]


def test_ac068_finding_zigzag_and_overspeed_correlated(tmp_path):
    obj = _base_obj(speed_kmh=90, forecast_lat_40=46.61, forecast_lon_40=14.30,
                    forecast_lat_60=46.61, forecast_lon_60=14.45)
    _write_frame(tmp_path, "2026-08-05_07-55-00", [obj])
    r = ac068(tmp_path)
    assert r["status"] == "finding"
    assert "zusammenhaengender Befund" in r["beleg"]


def test_ac068_finding_near_speed_cap(tmp_path):
    _write_frame(tmp_path, "2026-08-05_08-00-00", [_base_obj(speed_kmh=148)])
    r = ac068(tmp_path)
    assert r["status"] == "finding"
    assert "Clamping-Verdacht" in r["beleg"]


def test_ac068_respects_runtime_override_for_cap(tmp_path):
    d = tmp_path / "config"
    d.mkdir(parents=True, exist_ok=True)
    (d / "effective_runtime_config.json").write_text(
        json.dumps({"MAX_CELL_SPEED_KMH": 200.0}), encoding="utf-8")
    _write_frame(tmp_path, "2026-08-05_08-05-00", [_base_obj(speed_kmh=148)])
    r = ac068(tmp_path)
    # 148 < 60 wäre ok, aber 148 > 60 loest weiterhin Overspeed aus; Cap-Warnung
    # darf mit dem hoeheren Override aber nicht mehr anschlagen.
    assert "Clamping-Verdacht" not in r["beleg"]
