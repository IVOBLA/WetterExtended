import hydro_flood_ml as h


def test_refresh_hydro_fields_marks_forecast_stale():
    cached={'generated_at':'2026-01-01T00:00:00Z','payload_scope':'public','stations':[{'station_id':'1','current_q_m3s':1.0,'station_q_threshold_m3s':5.0,'predicted_q_delta_m3s':2.0}]}
    live={'fetched_at':'2026-01-01T01:00:00Z','stations':[{'station_id':'1','q_m3s':3.0,'measured_at':'2026-01-01T01:00:00Z','data_age_min':1}]}
    out=h.refresh_hydro_fields_in_cached_risk(cached, live)
    row=out['stations'][0]
    assert row['current_q_m3s'] == 3.0
    assert row['current_q_distance_to_threshold_m3s'] == 2.0
    assert row['predicted_q_delta_m3s'] == 2.0
    assert row['forecast_evaluation_stale'] is True
