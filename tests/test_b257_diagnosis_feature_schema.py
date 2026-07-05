"""B257: Diagnose nutzt aktive Feldnamen → echte Wetter-/Gelände-Features sind nicht 'missing'."""
import json
from datetime import datetime, timezone
from pathlib import Path

from tools.diagnose_forecast_quality import build_diagnosis


def _write_details(ev: Path):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rec = {
        "verified_at_utc": now,
        "forecast_created_at_utc": now,
        "target_timestamp_utc": now,
        "horizon_min": 10,
        "object_id": "OBJ1", "cell_id": "WX-TEST-0001",
        "forecast_lat": 46.40, "forecast_lon": 13.40,
        "actual_lat": 46.41, "actual_lon": 13.41,
        "forecast_error_km": 1.23, "match_type": "id",
        "no_target_frame": False,
        # B249-Schema (echte Feldnamen):
        "dem_elevation_m": 1606.9, "dem_slope_toward_cell": 0.12,
        "dem_barrier_ahead": 0.0, "dem_slope_barrier_status": "no_movement_vector",
        "valley_alignment": 0.5,
        "terrain_blocking_score": 0.0, "orographic_lift_score": 0.0,
        "wind_speed_700hPa": 20.5, "wind_speed_500hPa": 26.3,
        "wind_dir_cos": 0.99, "wind_dir_sin": 0.03,
        "cape": 25.6, "arome_li": 0.9, "arome_t2m": 10.1,
        "nowcast_rr_mm15": 1.91, "lightning_count_10km": 0.0,
    }
    (ev / "forecast_error_details.jsonl").write_text(
        json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def test_active_schema_features_present(tmp_path):
    ev = tmp_path / "evaluation"
    ev.mkdir()
    _write_details(ev)

    diag = build_diagnosis(tmp_path, hours=24, evaluation_dir=ev)

    wf = diag["weather_features"]
    # Aktive Wetterfelder müssen erkannt werden (nicht 'missing'):
    for key in ("wind_speed_700hPa", "cape", "arome_t2m"):
        assert wf[key]["present_samples"] == 1, f"{key} sollte vorhanden sein"
        assert wf[key]["missing_ratio"] == 0.0, f"{key} darf nicht missing sein"

    # Legacy-Schlüssel dürfen NICHT mehr geprüft werden:
    for legacy in ("wind_speed", "temperature", "grosswetterlage"):
        assert legacy not in wf, f"Legacy-Schlüssel {legacy} sollte entfernt sein"

    assert diag["dem_slope_barrier_status_breakdown"] == {
        "computed": 0, "no_movement_vector": 1,
        "dem_partial_coverage": 0, "dem_unavailable": 0
    }

    terr = diag["dem_orography"]
    assert terr["valley_alignment"]["present_samples"] == 1
    assert "valley_alignment_score" not in terr
    assert "valley_channeling_score" not in terr
