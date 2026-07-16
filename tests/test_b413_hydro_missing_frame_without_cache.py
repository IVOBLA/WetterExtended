import hydro_flood_ml as h


def test_missing_frame_without_cache_returns_live_stations(monkeypatch):
    monkeypatch.setattr(h, "load_q_trend_history", lambda: {})
    live={"fetched_at":"2026-07-16T10:00:00Z","stations":[{"station_id":"S","name":"Pegel","q_m3s":4,"mark_q_m3s":10,"measured_at":"2026-07-16T09:59:00Z"}]}
    doc=h.build_deferred_public_risk(live, {"status":"missing"}, None)
    assert doc["status"] == "deferred_missing_cell_snapshot"
    row=doc["stations"][0]
    assert row["current_q_m3s"] == 4
    assert row["forecast_flood_evaluable"] is False
    assert row["precip_status"] != "no_relevant_cell"


def test_fresh_empty_frame_is_no_relevant_cell(monkeypatch):
    monkeypatch.setattr(h, "record_pending_samples", lambda *a, **k: {"pending_added":0})
    monkeypatch.setattr(h, "materialize_pending_samples", lambda *a, **k: {"labeled_added":0})
    live={"cell_frame_meta":{"status":"ok","raw_cell_count":0},"stations":[{"station_id":"S","q_m3s":4,"mark_q_m3s":10}]}
    row=h.evaluate_live_flood_risk(stations=live["stations"], live=live, cells=[], write=False)["stations"][0]
    assert row["precip_status"] == "no_relevant_cell"
    assert row["precip_evaluable"] is True
