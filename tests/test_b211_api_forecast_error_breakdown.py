import json
import pytest
pytest.importorskip("flask")


def test_api_forecast_error_breakdown_present_and_missing(monkeypatch, tmp_path):
    import app as app_module
    ev = tmp_path / "evaluation"; ev.mkdir()
    monkeypatch.setitem(app_module.SAVE_PATHS, "evaluation", str(ev))
    client = app_module.app.test_client()
    missing = client.get("/api/forecast_error_breakdown")
    assert missing.status_code == 200
    assert missing.get_json()["status"] == "missing"
    (ev / "accuracy_history.jsonl").write_text(json.dumps({"timestamp_utc":"2026-01-01T00:00:00Z","breakdown_by_forecast_mode":{"10":{"ml":{"verified":1}}},"diagnosis":["x"]})+"\n", encoding="utf-8")
    ok = client.get("/api/forecast_error_breakdown")
    assert ok.status_code == 200
    data = ok.get_json()
    assert data["status"] == "ok"
    assert data["breakdown_by_forecast_mode"]["10"]["ml"]["verified"] == 1
