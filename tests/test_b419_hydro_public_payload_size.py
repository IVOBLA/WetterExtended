import json
import hydro_flood_ml as h

REMOVED = {"ml_predicted_q_delta_m3s", "physical_predicted_q_delta_m3s", "physical_predicted_q_max_m3s", "raw_overlap_area_km2_sum", "overlap_deduplicated_area_km2", "cell_catchment_overlap_area_km2_sum", "effective_overlap_area_km2", "max_overlap_area_km2", "spatial_dedup_applied", "total_rain_volume_m3", "total_runoff_volume_m3", "model_source", "hydro_flood_risk_score", "flood_probability"}
B413 = {"current_q_above_threshold", "current_threshold_evaluable", "forecast_flood_evaluable", "forecast_evaluation_stale", "forecast_evaluation_generated_at", "forecast_evaluation_age_min", "stale_predicted_q_max_m3s", "stale_prediction_generated_at"}


def test_public_allowlist_keeps_contract_and_removes_internals(capsys):
    row = {key: 1 for key in REMOVED | B413}
    row.update({"station_id": "1", "observed_precip_used_in_forecast": False, "cell_diagnostics": [], "station_runoff_series": [], "model_signature": "x"})
    public = h._public_flood_row(row)
    assert not REMOVED & public.keys()
    assert B413 <= public.keys()
    assert "observed_precip_used_in_forecast" in public
    assert not {"cell_diagnostics", "station_runoff_series", "model_signature"} & public.keys()
    before = len(json.dumps({"stations": [row] * 50}))
    after = len(json.dumps({"stations": [public] * 50}))
    print(f"B419 payload 50 stations: before={before} bytes after={after} bytes fields={len(public)}")
    assert after < before
