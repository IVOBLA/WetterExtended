"""P75: Bereits durchgezogener Zellniederschlag wirkt im Routing nach."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import pytest
hydro_flood_ml = pytest.importorskip("hydro_flood_ml")

@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_ML_DIR", tmp_path, raising=False)
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_SAMPLE_DB_PATH", tmp_path / "s.sqlite3", raising=False)
    monkeypatch.setattr(hydro_flood_ml, "_DEFAULT_HYDRO_SAMPLE_DB_PATH", tmp_path / "s.sqlite3", raising=False)
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_DATASET_JSONL_PATH", tmp_path / "d.jsonl", raising=False)
    monkeypatch.setattr(hydro_flood_ml, "_DEFAULT_HYDRO_DATASET_JSONL_PATH", tmp_path / "d.jsonl", raising=False)
    return tmp_path

def _write(frame_ts, cell_id="c1", rate=12.0, area=4.0):
    hydro_flood_ml.append_precip_ledger([{"station_id": "9001", "cell_id": cell_id, "eff_overlap_area_km2": area, "rain_rate_mm_h": rate, "rain_rate_source": "nowcast_rain_rate_1h", "runoff_coeff": 0.4, "raw_delta_q_m3s": round(0.4 * rate * area / 3.6, 5)}], frame_ts)

def _ts(base, minutes):
    return (base - timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")
BASE = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)

def test_current_frame_is_never_read_from_ledger(db):
    now_ts = _ts(BASE, 0); _write(now_ts); _write(_ts(BASE, 10))
    rows = hydro_flood_ml.load_precip_ledger(now_ts).get("9001", [])
    assert [r["frame_timestamp"] for r in rows] == [_ts(BASE, 10)]

def test_ledger_respects_retention(db, monkeypatch):
    monkeypatch.setattr(hydro_flood_ml, "ledger_retention_min", lambda: 60)
    _write(_ts(BASE, 30), cell_id="fresh"); _write(_ts(BASE, 400), cell_id="old")
    assert {r["cell_id"] for r in hydro_flood_ml.load_precip_ledger(_ts(BASE, 0)).get("9001", [])} == {"fresh"}

def test_recent_frame_never_lands_on_offset_zero(db):
    rows = [{"frame_timestamp": _ts(BASE, 2), "cell_id": "c1", "minutes_ago": 2.0, "eff_overlap_area_km2": 4.0, "rain_rate_mm_h": 12.0, "raw_delta_q_m3s": 5.3}]
    ante = hydro_flood_ml._antecedent_from_ledger(rows, 5, 180, 0.4)
    assert all(off <= -5 for off in ante["hist_by_off"])

def test_multiple_frames_in_one_bucket_are_averaged_not_summed(db):
    rows = [{"frame_timestamp": "a", "cell_id": "c1", "minutes_ago": 9.0, "eff_overlap_area_km2": 1.0, "rain_rate_mm_h": 10.0, "raw_delta_q_m3s": 4.0}, {"frame_timestamp": "b", "cell_id": "c1", "minutes_ago": 11.0, "eff_overlap_area_km2": 1.0, "rain_rate_mm_h": 10.0, "raw_delta_q_m3s": 6.0}]
    assert hydro_flood_ml._antecedent_from_ledger(rows, 5, 180, 0.4)["hist_by_off"][-10] == pytest.approx(5.0)

def test_frame_gap_is_capped(db, monkeypatch):
    monkeypatch.setattr(hydro_flood_ml, "_cfg_int", lambda name, d, lo, hi: 20 if name == "HYDRO_LEDGER_MAX_GAP_MIN" else d)
    rows = [{"frame_timestamp": "a", "cell_id": "c1", "minutes_ago": 170.0, "eff_overlap_area_km2": 1.0, "rain_rate_mm_h": 12.0, "raw_delta_q_m3s": 1.0}, {"frame_timestamp": "b", "cell_id": "c1", "minutes_ago": 10.0, "eff_overlap_area_km2": 1.0, "rain_rate_mm_h": 12.0, "raw_delta_q_m3s": 1.0}]
    ante = hydro_flood_ml._antecedent_from_ledger(rows, 5, 180, 0.4)
    assert ante["antecedent_rain_volume_m3"] == pytest.approx(8000.0, rel=0.01)
    assert ante["antecedent_max_gap_min"] == pytest.approx(160.0)

def test_empty_history_is_neutral(db):
    ante = hydro_flood_ml._antecedent_from_ledger([], 5, 180, 0.4)
    assert ante["hist_by_off"] == {} and ante["antecedent_status"] == "no_history"
    assert ante["antecedent_runoff_volume_m3"] == 0.0

def test_departed_cell_still_contributes(db):
    rows = [{"frame_timestamp": f"f{i}", "cell_id": "c1", "minutes_ago": float(m), "eff_overlap_area_km2": 5.0, "rain_rate_mm_h": 20.0, "raw_delta_q_m3s": 11.1} for i, m in enumerate([25, 20, 15, 10])]
    ante = hydro_flood_ml._antecedent_from_ledger(rows, 5, 180, 0.4)
    assert ante["antecedent_status"] == "ok" and ante["antecedent_cell_count"] == 1 and ante["antecedent_frame_count"] == 4
    assert ante["antecedent_last_hit_age_min"] == pytest.approx(10.0) and ante["antecedent_runoff_volume_m3"] > 0
    assert sorted(ante["hist_by_off"]) == [-25, -20, -15, -10]

def test_schema_version_bumped(): assert hydro_flood_ml.FEATURE_SCHEMA_VERSION == "p75_antecedent_v1"
def test_new_features_are_in_schema():
    for name in ("antecedent_rain_volume_m3", "antecedent_runoff_volume_m3", "antecedent_routed_delta_q_m3s", "antecedent_cell_count", "antecedent_frame_count", "antecedent_last_hit_age_min", "antecedent_available_flag"):
        assert name in hydro_flood_ml.HYDRO_FLOOD_ML_FEATURES

def test_missing_antecedent_age_is_not_imputed_as_fresh():
    snap = hydro_flood_ml._feature_snapshot({"antecedent_status": "no_history", "contributing_cell_count": 0})
    assert snap["antecedent_available_flag"] == 0.0 and snap["antecedent_last_hit_age_min"] >= 1000

def test_debug_only_keys_stay_out_of_public_payload():
    public = hydro_flood_ml._public_flood_row({"station_id": "9001", "antecedent_series": [{"offset_min": -5}], "precip_ledger_t0": [{"cell_id": "c1"}], "antecedent_status": "ok", "generated_at": "x"})
    assert "antecedent_series" not in public and "precip_ledger_t0" not in public and public["antecedent_status"] == "ok"

def test_build_feature_row_forwards_ledger_rows_unchanged(monkeypatch):
    received = {}

    def fake_precip(station, cells, ledger_rows=None):
        received["ledger_rows"] = ledger_rows
        return {
            "cell_precip_source_type": "none",
            "cell_catchment_precip_sum_mm": 0.0,
            "cell_catchment_precip_weighted_sum_mm": 0.0,
            "cell_catchment_max_intensity": 0.0,
        }

    monkeypatch.setattr(hydro_flood_ml, "_precip_from_cells", fake_precip)
    ledger = [{"frame_timestamp": "unique", "cell_id": "ledger-cell"}]

    hydro_flood_ml.build_feature_row({"station_id": "9001"}, cells=[], ledger_rows=ledger)

    assert received["ledger_rows"] is ledger
