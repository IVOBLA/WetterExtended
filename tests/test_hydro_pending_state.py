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
