import config
import hydro_flood_ml as h


def _cell(delta=1.0):
    return {"physical_predicted_q_delta_m3s": delta, "physical_predicted_q_max_m3s": 6.0,
            "total_rain_volume_m3": 2000.0, "total_runoff_volume_m3": 800.0,
            "catchment_area_geometry_km2": 2.0, "contributing_cell_count": 1}


def _obs(**changes):
    value = {"observed_precip_available": True, "observed_precip_source_quality": "high",
             "observed_precip_data_age_min": 0.0, "observed_precip_measurement_window_min": 60.0,
             "observed_catchment_precip_sum_mm": 3.0}
    value.update(changes)
    return value


def test_high_quality_measurement_forces_q_and_balances_volume():
    result = h._apply_observed_precip_forcing({"q_m3s": 5, "catchment_area_km2": 2}, _obs(), _cell())
    assert result["observed_precip_used_in_forecast"] is True
    assert result["physical_predicted_q_delta_m3s"] > 1.0
    assert result["observed_precip_rain_volume_m3"] == 6000.0
    assert result["combined_rain_volume_m3"] == 8000.0
    assert result["precip_window_overlap_min"] == 0.0


def test_rejections_are_explicit():
    cases = [(_obs(observed_precip_source_quality="medium"), "observed_precip_quality_not_high"),
             (_obs(observed_precip_data_age_min=10000), "observed_precip_outside_lag_window")]
    for obs, reason in cases:
        result = h._apply_observed_precip_forcing({"q_m3s": 5, "catchment_area_km2": 2}, obs, _cell())
        assert result["observed_precip_used_in_forecast"] is False
        assert result["observed_precip_rejection_reason"] == reason
        assert result["physical_predicted_q_delta_m3s"] == 1.0
    assert h._apply_observed_precip_forcing({"q_m3s": 5}, _obs(), {**_cell(), "catchment_area_geometry_km2": None})["observed_precip_rejection_reason"] == "catchment_area_missing"


def test_overlap_is_reported_and_not_forced():
    result = h._apply_observed_precip_forcing({"q_m3s": 5, "catchment_area_km2": 2}, _obs(observed_precip_data_age_min=-5), _cell())
    assert result["precip_window_overlap_min"] == 5.0
    assert result["observed_precip_used_in_forecast"] is False


def test_new_features_are_optional_and_source_flags_can_coexist():
    row = {name: 1.0 for name in h.HYDRO_FLOOD_ML_FEATURES}
    row.update(observed_precip_available=True, observed_precip_used_in_forecast=True, contributing_cell_count=1)
    snap = h._feature_snapshot(row)
    assert snap["precip_source_measured_flag"] == snap["precip_source_cell_forecast_flag"] == 1.0
    for name in config.HYDRO_FLOOD_ML_FEATURES[-8:]:
        assert name not in h.HYDRO_REQUIRED_FEATURES
