import hydro_verification as hv


def test_classifies_plausible_rise_as_confirmed(monkeypatch):
    monkeypatch.setattr(hv, "load_pending_hydro_impacts", lambda: [])
    result = hv.classify_hydro_response({"station_id": "S1", "cell_id": 1}, {
        "raw_data_status": "ok", "delta_q_m3s": 0.6, "relative_delta_q_pct": 50,
        "delta_w_cm": 7, "relative_delta_w_pct": 15,
    })

    assert result["status"] == "confirmed"
    assert "plausiblen Zusammenhang" in " ".join(result["reason"])


def test_classifies_no_rise_as_rejected(monkeypatch):
    monkeypatch.setattr(hv, "load_pending_hydro_impacts", lambda: [])
    result = hv.classify_hydro_response({"station_id": "S1", "cell_id": 1}, {
        "raw_data_status": "ok", "delta_q_m3s": 0.01, "relative_delta_q_pct": 1,
        "delta_w_cm": 1, "relative_delta_w_pct": 2,
    })

    assert result["status"] == "rejected"
    assert "nicht bestätigt" in " ".join(result["reason"])
