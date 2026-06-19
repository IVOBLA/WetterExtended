from datetime import datetime, timezone
import json

import hydro_verification as hv


def _write_snapshot(tmp_path, stamp, q, w):
    (tmp_path / f"hydro_{stamp}.json").write_text(json.dumps({
        "fetched_at": stamp,
        "stations": [{"station_id": "S1", "q_m3s": q, "w_cm": w, "measured_at": stamp}],
    }), encoding="utf-8")


def test_pending_events_are_not_verified_too_early(tmp_path, monkeypatch):
    out = tmp_path / "verifications.jsonl"
    monkeypatch.setattr(hv, "HYDRO_VERIFICATION_PATH", out)
    monkeypatch.setattr(hv, "HYDRO_LIVE_DIR", tmp_path)
    monkeypatch.setattr(hv, "load_pending_hydro_impacts", lambda: [{
        "event_id": "e1", "station_id": "S1", "cell_id": 42,
        "created_at": "2026-06-19T10:00:00Z", "estimated_lag_min": [20, 180], "status": "pending",
    }])

    result = hv.verify_pending_hydro_impacts(datetime(2026, 6, 19, 11, 0, tzinfo=timezone.utc))

    assert result[0]["status"] == "pending"
    assert "noch nicht abgeschlossen" in result[0]["reason"][0]
    assert out.exists()


def test_compute_hydro_delta_and_summary_write(tmp_path, monkeypatch):
    monkeypatch.setattr(hv, "HYDRO_LIVE_DIR", tmp_path)
    monkeypatch.setattr(hv, "HYDRO_VERIFICATION_PATH", tmp_path / "verifications.jsonl")
    monkeypatch.setattr(hv, "HYDRO_VERIFICATION_SUMMARY_PATH", tmp_path / "hydro_verification_summary.json")
    _write_snapshot(tmp_path, "2026-06-19T10:00:00Z", 1.0, 40)
    _write_snapshot(tmp_path, "2026-06-19T10:40:00Z", 1.7, 48)

    delta = hv.compute_hydro_delta("S1", "2026-06-19T10:20:00Z", 60)

    assert delta["delta_q_m3s"] == 0.7
    assert delta["delta_w_cm"] == 8.0

    hv.save_hydro_verification({
        "event_id": "e1", "station_id": "S1", "cell_id": 1, "verified_at": "2026-06-19T12:00:00Z",
        "status": "confirmed", "lag_window_min": [20, 180],
        "observed": {"delta_q_m3s": 0.7, "delta_w_cm": 8}, "confidence": "high", "reason": ["test"],
    })
    summary = hv.get_hydro_verification_summary(days=3650)

    assert summary["stations"]["S1"]["confirmed"] == 1
    assert (tmp_path / "hydro_verification_summary.json").exists()
