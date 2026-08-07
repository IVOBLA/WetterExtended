"""P116 — Admin-Schalter und deterministischer Reifegrad-Bericht."""
import json
from pathlib import Path
import app as app_module
import runtime_config

REPO = Path(__file__).resolve().parents[1]
JSX = REPO / "frontend" / "src" / "pages" / "AiSuggestions.jsx"


def _jsx():
    return JSX.read_text(encoding="utf-8")


def test_new_endpoint_inherits_admin_protection():
    assert "/api/local_analysis" in app_module._ADMIN_WRITE_PREFIXES
    assert "/api/local_analysis" in app_module._SENSITIVE_READ_PREFIXES
    assert "/api/local_analysis/forecast_experiments".startswith("/api/local_analysis")


def test_get_returns_defaults_and_readiness(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime_config, "get", lambda name, default=None: default)
    monkeypatch.setattr(app_module, "SAVE_PATHS", {"evaluation": str(tmp_path)})
    with app_module.app.test_request_context("/api/local_analysis/forecast_experiments"):
        data = app_module.api_local_analysis_forecast_experiments_get().get_json()
    assert data["enabled"] is False
    assert "overall_ready" in data["readiness"]
    assert len(data["readiness"]["criteria"]) == 5


def test_get_reflects_runtime_override(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime_config, "get", lambda name, default=None: True if name == "FORECAST_EXPERIMENTS_ENABLED" else default)
    monkeypatch.setattr(app_module, "SAVE_PATHS", {"evaluation": str(tmp_path)})
    with app_module.app.test_request_context("/api/local_analysis/forecast_experiments"):
        data = app_module.api_local_analysis_forecast_experiments_get().get_json()
    assert data["enabled"] is True


def test_get_reads_real_accuracy_history(monkeypatch, tmp_path):
    (tmp_path / "accuracy_history.jsonl").write_text(json.dumps({"samples": 100, "verified": 96, "ambiguous_nearest": 1}) + "\n", encoding="utf-8")
    monkeypatch.setattr(runtime_config, "get", lambda name, default=None: default)
    monkeypatch.setattr(app_module, "SAVE_PATHS", {"evaluation": str(tmp_path)})
    with app_module.app.test_request_context("/api/local_analysis/forecast_experiments"):
        data = app_module.api_local_analysis_forecast_experiments_get().get_json()
    assert next(c for c in data["readiness"]["criteria"] if c["id"] == "gold_match_coverage")["ok"] is True


def test_post_toggle_calls_patch(monkeypatch):
    patched = {}
    monkeypatch.setattr(runtime_config, "patch", lambda d: patched.update(d) or d)
    with app_module.app.test_request_context("/api/local_analysis/forecast_experiments", method="POST", data=json.dumps({"enabled": True}), content_type="application/json"):
        app_module.api_local_analysis_forecast_experiments_save()
    assert patched.get("FORECAST_EXPERIMENTS_ENABLED") is True


def test_post_rejects_missing_field():
    with app_module.app.test_request_context("/api/local_analysis/forecast_experiments", method="POST", data=json.dumps({}), content_type="application/json"):
        resp = app_module.api_local_analysis_forecast_experiments_save()
    assert isinstance(resp, tuple)
    assert resp[1] == 400


def test_toggle_present_in_local_analysis_card():
    section = _jsx().split("Lokale Analyse am Pi", 1)[1].split("HitL", 1)[0]
    assert "toggleForecastExperiments" in section
    assert "Kinematik-Shadow-Experimente aktiviert" in section


def test_forecast_experiments_fetched_on_mount():
    assert "/api/local_analysis/forecast_experiments" in _jsx()


def test_readiness_criteria_rendered():
    section = _jsx().split("Lokale Analyse am Pi", 1)[1].split("HitL", 1)[0]
    assert all(word in section for word in ("readiness", "overall_ready", "criteria"))


def test_enabling_while_not_ready_asks_for_confirmation():
    full = _jsx()
    start = full.index("async function toggleForecastExperiments")
    body = full[start:start + 800]
    assert "window.confirm" in body
    assert "overall_ready" in body
