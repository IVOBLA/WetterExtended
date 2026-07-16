import hydro_flood_ml as h


def test_public_row_contains_threshold_state_without_model_signature():
    row=h._public_flood_row({"station_id":"S","current_q_above_threshold":True,"current_threshold_evaluable":True,"forecast_flood_evaluable":False,"forecast_evaluation_stale":True,"forecast_evaluation_generated_at":"x","forecast_evaluation_age_min":1,"model_sha256":"secret","model_signature":"secret"})
    assert row["current_q_above_threshold"] is True
    assert row["current_threshold_evaluable"] is True
    assert row["forecast_flood_evaluable"] is False
    assert row["forecast_evaluation_stale"] is True
    assert "model_sha256" not in row
    assert "model_signature" not in row
