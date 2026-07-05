"""B301: dem_slope_barrier_status_breakdown muss alle vier Status-Werte
(inkl. dem_partial_coverage) konsistent zwischen Erzeuger und Verbrauchern
führen — Regression für das B300/B257-Schema-Drift."""
import json
from datetime import datetime, timezone
from pathlib import Path

from tools.diagnose_forecast_quality import build_diagnosis


def _write_details(ev: Path, status: str):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rec = {
        "verified_at_utc": now,
        "forecast_created_at_utc": now,
        "target_timestamp_utc": now,
        "horizon_min": 10,
        "object_id": "OBJ1", "cell_id": "WX-TEST-0301",
        "forecast_lat": 46.40, "forecast_lon": 13.40,
        "actual_lat": 46.41, "actual_lon": 13.41,
        "forecast_error_km": 1.23, "match_type": "id",
        "no_target_frame": False,
        "dem_elevation_m": 1606.9, "dem_slope_toward_cell": 0.0,
        "dem_barrier_ahead": 0.0, "dem_slope_barrier_status": status,
        "valley_alignment": 0.0,
        "terrain_blocking_score": 0.0, "orographic_lift_score": 0.0,
        "wind_speed_700hPa": 20.5, "wind_speed_500hPa": 26.3,
        "wind_dir_cos": 0.99, "wind_dir_sin": 0.03,
        "cape": 25.6, "arome_li": 0.9, "arome_t2m": 10.1,
        "nowcast_rr_mm15": 1.91, "lightning_count_10km": 0.0,
    }
    (ev / "forecast_error_details.jsonl").write_text(
        json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def test_dem_partial_coverage_counted_in_breakdown(tmp_path):
    ev = tmp_path / "evaluation"
    ev.mkdir()
    _write_details(ev, "dem_partial_coverage")

    diag = build_diagnosis(tmp_path, hours=24, evaluation_dir=ev)

    assert diag["dem_slope_barrier_status_breakdown"] == {
        "computed": 0, "no_movement_vector": 0,
        "dem_partial_coverage": 1, "dem_unavailable": 0
    }


def test_all_four_status_keys_always_present(tmp_path):
    """Auch bei nur einem Status-Wert im Datensatz müssen alle vier
    Schlüssel im Breakdown auftauchen (mit 0 für nicht beobachtete)."""
    ev = tmp_path / "evaluation"
    ev.mkdir()
    _write_details(ev, "computed")

    diag = build_diagnosis(tmp_path, hours=24, evaluation_dir=ev)

    breakdown = diag["dem_slope_barrier_status_breakdown"]
    assert set(breakdown.keys()) == {
        "computed", "no_movement_vector", "dem_partial_coverage", "dem_unavailable"
    }
    assert breakdown["computed"] == 1
