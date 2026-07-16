import hydro_flood_ml as h


def test_deferred_q_above_threshold_replaces_old_reasons():
    cached={"generated_at":"2026-07-16T09:00:00Z","stations":[{"station_id":"S","station_q_threshold_m3s":10,"flood_expected":False,"reasons":["old forecast"]}]}
    live={"fetched_at":"2026-07-16T10:00:00Z","cell_frame_meta":{"status":"stale"},"stations":[{"station_id":"S","q_m3s":11,"measured_at":"2026-07-16T10:00:00Z"}]}
    row=h.refresh_hydro_fields_in_cached_risk(cached, live)["stations"][0]
    assert row["flood_expected"] is True
    assert row["flood_evaluable"] is True
    assert row["forecast_flood_evaluable"] is False
    assert row["flood_status"] == "threshold_already_exceeded"
    assert row["reasons"] == ["current_q_m3s >= station_q_threshold_m3s"]


def test_deferred_old_forecast_warning_is_cleared_below_threshold():
    cached={"generated_at":"2026-07-16T09:00:00Z","stations":[{"station_id":"S","station_q_threshold_m3s":10,"predicted_q_max_m3s":12,"flood_expected":True,"reasons":["Niederschlag im oberliegenden Einzugsgebiet"]}]}
    live={"cell_frame_meta":{"status":"stale"},"stations":[{"station_id":"S","q_m3s":8}]}
    row=h.refresh_hydro_fields_in_cached_risk(cached, live)["stations"][0]
    assert row["flood_expected"] is False
    assert row["reasons"] == []
    assert row["predicted_q_max_m3s"] is None
    assert row["stale_predicted_q_max_m3s"] == 12
    assert row["flood_status"] == "deferred_stale_cell_snapshot"


def test_error_status_stays_distinct_from_invalid():
    doc=h.build_deferred_public_risk({"stations":[]}, {"status":"error"}, None)
    assert doc["status"] == "deferred_cell_snapshot_error"
