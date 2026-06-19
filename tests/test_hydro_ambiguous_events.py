import hydro_verification as hv


def test_measurement_gap_is_ambiguous_not_rejected(monkeypatch):
    monkeypatch.setattr(hv, "load_pending_hydro_impacts", lambda: [])
    result = hv.classify_hydro_response({"station_id": "S1", "cell_id": 1}, {"raw_data_status": "gap"})

    assert result["status"] == "ambiguous"
    assert "Messlücke" in " ".join(result["reason"])


def test_competing_cells_are_ambiguous(monkeypatch):
    event = {"event_id": "e1", "station_id": "S1", "cell_id": 1, "created_at": "2026-06-19T10:00:00Z", "estimated_lag_min": [20, 180]}
    competing = {"event_id": "e2", "station_id": "S1", "cell_id": 2, "created_at": "2026-06-19T10:30:00Z", "estimated_lag_min": [20, 180]}
    monkeypatch.setattr(hv, "load_pending_hydro_impacts", lambda: [event, competing])

    result = hv.classify_hydro_response(event, {
        "raw_data_status": "ok", "delta_q_m3s": 1.0, "relative_delta_q_pct": 80,
        "delta_w_cm": 10, "relative_delta_w_pct": 25,
    })

    assert result["status"] == "ambiguous"
    assert "konkurrierende Zellen" in " ".join(result["reason"])
