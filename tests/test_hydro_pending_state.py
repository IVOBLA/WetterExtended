import json
from datetime import datetime, timezone

import hydro_impact
import hydro_verification as hv


def test_load_pending_hydro_impacts_dedupes_and_honors_state(tmp_path, monkeypatch):
    monkeypatch.setattr(hydro_impact, "IMPACT_DIR", tmp_path)
    monkeypatch.setattr(hydro_impact, "HYDRO_IMPACT_STATE_PATH", tmp_path / "hydro_impact_state.json")
    e1 = {"event_id": "e1", "status": "pending", "station_id": "S1", "cell_id": "C1"}
    e2 = {"event_id": "e2", "status": "pending", "station_id": "S1", "cell_id": "C2"}
    (tmp_path / "hydro_impact_2026-06-18.jsonl").write_text(json.dumps(e1) + "\n", encoding="utf-8")
    (tmp_path / "hydro_impact_2026-06-19.jsonl").write_text(json.dumps(e1 | {"cell_id": "C1b"}) + "\n" + json.dumps(e2) + "\n", encoding="utf-8")
    hydro_impact.save_hydro_impact_state("e1", {"status": "confirmed"})
    pending = hydro_impact.load_pending_hydro_impacts()
    assert [p["event_id"] for p in pending] == ["e2"]


def test_verification_persists_state_and_old_event_is_not_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(hydro_impact, "IMPACT_DIR", tmp_path)
    monkeypatch.setattr(hydro_impact, "HYDRO_IMPACT_STATE_PATH", tmp_path / "hydro_impact_state.json")
    monkeypatch.setattr(hydro_impact, "LATEST_IMPACTS_PATH", tmp_path / "latest_hydro_impacts.json")
    monkeypatch.setattr(hv, "HYDRO_VERIFICATION_PATH", tmp_path / "hydro_verifications.jsonl")
    monkeypatch.setattr(hv, "HYDRO_LIVE_DIR", tmp_path / "live")
    event = {"event_id": "e1", "status": "pending", "station_id": "S1", "cell_id": "C1", "created_at": "2026-06-19T08:00:00Z", "estimated_lag_min": [0, 1]}
    (tmp_path / "hydro_impact_2026-06-19.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")
    monkeypatch.setattr(hv, "compute_hydro_delta", lambda *a, **k: {"raw_data_status": "ok", "delta_q_m3s": 9})
    hv.verify_pending_hydro_impacts(datetime(2026, 6, 19, 9, 0, tzinfo=timezone.utc))
    assert hydro_impact.load_pending_hydro_impacts() == []


def test_load_pending_hydro_impacts_filters_verified_state_from_multi_event_jsonl(tmp_path, monkeypatch):
    monkeypatch.setattr(hydro_impact, "IMPACT_DIR", tmp_path)
    monkeypatch.setattr(hydro_impact, "HYDRO_IMPACT_STATE_PATH", tmp_path / "hydro_impact_state.json")
    events = [
        {"event_id": "confirmed-old", "status": "pending", "station_id": "S1", "cell_id": "C1"},
        {"event_id": "rejected-old", "status": "pending", "station_id": "S1", "cell_id": "C2"},
        {"event_id": "ambiguous-old", "status": "pending", "station_id": "S1", "cell_id": "C3"},
        {"event_id": "still-pending", "status": "pending", "station_id": "S1", "cell_id": "C4"},
    ]
    (tmp_path / "hydro_impact_2026-06-19.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "hydro_impact_state.json").write_text(json.dumps({
        "events": {
            "confirmed-old": {"status": "confirmed"},
            "rejected-old": {"status": "rejected"},
            "ambiguous-old": {"status": "ambiguous"},
        }
    }), encoding="utf-8")

    first_cycle = hydro_impact.load_pending_hydro_impacts()
    second_cycle = hydro_impact.load_pending_hydro_impacts()

    assert [event["event_id"] for event in first_cycle] == ["still-pending"]
    assert second_cycle == first_cycle


def test_confirmed_old_event_does_not_compete_with_new_pending_event(tmp_path, monkeypatch):
    monkeypatch.setattr(hydro_impact, "IMPACT_DIR", tmp_path)
    monkeypatch.setattr(hydro_impact, "HYDRO_IMPACT_STATE_PATH", tmp_path / "hydro_impact_state.json")
    old_confirmed = {
        "event_id": "old-confirmed",
        "status": "pending",
        "station_id": "S1",
        "cell_id": "old-cell",
        "created_at": "2026-06-19T10:00:00Z",
        "estimated_lag_min": [20, 180],
    }
    new_pending = {
        "event_id": "new-pending",
        "status": "pending",
        "station_id": "S1",
        "cell_id": "new-cell",
        "created_at": "2026-06-19T10:30:00Z",
        "estimated_lag_min": [20, 180],
    }
    (tmp_path / "hydro_impact_2026-06-19.jsonl").write_text(
        json.dumps(old_confirmed) + "\n" + json.dumps(new_pending) + "\n",
        encoding="utf-8",
    )
    hydro_impact.save_hydro_impact_state("old-confirmed", {"status": "confirmed"})

    result = hv.classify_hydro_response(new_pending, {
        "raw_data_status": "ok",
        "delta_q_m3s": 1.0,
        "relative_delta_q_pct": 80,
        "delta_w_cm": 10,
        "relative_delta_w_pct": 25,
    })

    assert result["status"] == "confirmed"
    assert "competing_cells_same_catchment" not in result["reason"]
