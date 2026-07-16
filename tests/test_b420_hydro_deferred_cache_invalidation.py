import hydro_flood_ml as h


def _stable_hash_dependencies(monkeypatch):
    monkeypatch.setattr(h, "_path_mtime", lambda path: None)
    monkeypatch.setattr(h, "_trend_cache_signature", lambda: {})
    monkeypatch.setattr(h, "model_stat_signature", lambda path: {})


def test_deferred_cache_tracks_frame_recovery_but_not_age(monkeypatch):
    _stable_hash_dependencies(monkeypatch)
    live = {"fetched_at": "2026-01-01T00:00:00Z", "stations": []}
    missing = {"status": "missing", "frame_timestamp": None, "raw_cell_count": 0, "frame_age_min": 5}
    doc = {"payload_scope": "public", "input_hash": h.flood_risk_input_hash(live, [], missing)}

    assert h.is_flood_risk_cache_valid(doc, live, [], missing)
    assert not h.is_flood_risk_cache_valid(
        doc, live, [], {"status": "ok", "frame_timestamp": "2026-01-01T00:01:00Z", "raw_cell_count": 0}
    )

    ok = {"status": "ok", "frame_timestamp": "2026-01-01T00:01:00Z", "raw_cell_count": 1, "frame_age_min": 1}
    ok_doc = {"payload_scope": "public", "input_hash": h.flood_risk_input_hash(live, [{}], ok)}
    assert not h.is_flood_risk_cache_valid(ok_doc, live, [{}], {**ok, "status": "stale"})
    assert h.is_flood_risk_cache_valid(ok_doc, live, [{}], {**ok, "frame_age_min": 20})
    assert isinstance(h.flood_risk_input_hash(live, []), str)


def test_recovered_empty_frame_is_regular_evaluation(monkeypatch):
    _stable_hash_dependencies(monkeypatch)
    monkeypatch.setattr(h, "load_q_trend_history", lambda: {})
    monkeypatch.setattr(h, "load_active_hydro_model", lambda: {})
    monkeypatch.setattr(h, "build_feature_row", lambda *a, **k: {"station_id": "A", "precip_status": "missing"})
    monkeypatch.setattr(h, "predict_q_delta", lambda *a, **k: {})
    monkeypatch.setattr(h, "heuristic_score", lambda *a, **k: {})
    monkeypatch.setattr(h, "readiness_status", lambda: {})
    live = {"stations": [], "cell_frame_meta": {"status": "ok", "cell_frame_status": "ok", "frame_timestamp": "t", "raw_cell_count": 0}}
    doc = h.evaluate_live_flood_risk(stations=[{"station_id": "A"}], live=live, cells=[], write=False)
    assert doc["stations"][0]["precip_status"] == "no_relevant_cell"
    assert "forecast_evaluation_stale" not in doc
    assert "deferred_reason" not in doc
