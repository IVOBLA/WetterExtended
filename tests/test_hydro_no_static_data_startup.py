import json

import hydro_api
from hydro_static_import import build_static_hydro


def test_missing_static_hydro_data_writes_status_and_is_not_fatal(tmp_path):
    status = build_static_hydro(str(tmp_path / "static"))
    assert status["status"] == "hydro_static_missing"
    assert "Hydro-Impact" in status["message"]
    saved = json.loads((tmp_path / "static/generated/hydro_static_status.json").read_text(encoding="utf-8"))
    assert saved["status"] == "hydro_static_missing"


def test_hydro_api_does_not_report_cache_error_as_success(tmp_path, monkeypatch):
    live = tmp_path / "hydro/live"
    generated = tmp_path / "hydro/static/generated"
    impact = tmp_path / "hydro/impact"
    live.mkdir(parents=True); generated.mkdir(parents=True); impact.mkdir(parents=True)
    (live / "latest_hydro.json").write_text(json.dumps({"stations": []}), encoding="utf-8")
    (live / "hydro_status.json").write_text(json.dumps({"ok": False, "from_cache": True, "last_error": "TimeoutError: offline"}), encoding="utf-8")
    monkeypatch.setattr(hydro_api, "LIVE_LATEST", live / "latest_hydro.json")
    monkeypatch.setattr(hydro_api, "LIVE_STATUS", live / "hydro_status.json")
    monkeypatch.setattr(hydro_api, "STATIC_GENERATED", generated)
    monkeypatch.setattr(hydro_api, "IMPACT_DIR", impact)
    monkeypatch.setattr(hydro_api, "LATEST_IMPACTS", impact / "latest_hydro_impacts.json")
    monkeypatch.setattr(hydro_api, "VERIFICATIONS", impact / "hydro_verifications.jsonl")

    status = hydro_api.status()
    assert status["live_ready"] is True
    assert status["from_cache"] is True
    assert status["live_ok"] is False
    assert status["status"] == "error"
    assert "offline" in status["last_error"]
