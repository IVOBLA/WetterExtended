"""P100 — Admin-Panel-Schalter fuer autonomes Tuning (Kill-Switch).

Prueft Backend-Endpunkte (direkter Funktionsaufruf, nicht ueber HTTP/Auth —
das Auth-Verhalten selbst ist bereits durch test_b464_analysis_admin_gate.py
abgedeckt: /api/local_analysis liegt in _ADMIN_WRITE_PREFIXES und
_SENSITIVE_READ_PREFIXES, der neue Endpunkt erbt diesen Schutz automatisch
per Praefix-Match) und Frontend-Verdrahtung.
"""
import json
from pathlib import Path

import app as app_module
import runtime_config

REPO = Path(__file__).resolve().parents[1]
JSX = REPO / "frontend" / "src" / "pages" / "AiSuggestions.jsx"


def _jsx():
    return JSX.read_text(encoding="utf-8")


def test_new_endpoint_inherits_admin_protection():
    """/api/local_analysis/tuning erbt den Schutz von /api/local_analysis."""
    assert "/api/local_analysis" in app_module._ADMIN_WRITE_PREFIXES
    assert "/api/local_analysis" in app_module._SENSITIVE_READ_PREFIXES
    assert "/api/local_analysis/tuning".startswith("/api/local_analysis")


def test_get_tuning_status_returns_defaults(monkeypatch):
    monkeypatch.setattr(runtime_config, "get", lambda name, default=None: default)
    with app_module.app.test_request_context("/api/local_analysis/tuning"):
        resp = app_module.api_local_analysis_tuning_get()
    data = resp.get_json() if hasattr(resp, "get_json") else json.loads(resp.data)
    assert data["enabled"] is False
    assert len(data["params"]) == 11


def test_get_tuning_status_reflects_runtime_override(monkeypatch):
    monkeypatch.setattr(
        runtime_config, "get",
        lambda name, default=None: True if name == "AUTONOMOUS_TUNING_ENABLED" else default)
    with app_module.app.test_request_context("/api/local_analysis/tuning"):
        resp = app_module.api_local_analysis_tuning_get()
    data = resp.get_json() if hasattr(resp, "get_json") else json.loads(resp.data)
    assert data["enabled"] is True


def test_post_tuning_toggle_calls_patch(monkeypatch):
    patched = {}
    monkeypatch.setattr(runtime_config, "patch", lambda d: patched.update(d) or d)
    with app_module.app.test_request_context(
            "/api/local_analysis/tuning", method="POST",
            data=json.dumps({"enabled": True}), content_type="application/json"):
        resp = app_module.api_local_analysis_tuning_save()
    assert patched.get("AUTONOMOUS_TUNING_ENABLED") is True


def test_post_tuning_rejects_missing_field():
    with app_module.app.test_request_context(
            "/api/local_analysis/tuning", method="POST",
            data=json.dumps({}), content_type="application/json"):
        resp = app_module.api_local_analysis_tuning_save()
    assert isinstance(resp, tuple)
    assert resp[1] == 400


def test_history_endpoint_reads_jsonl(monkeypatch, tmp_path):
    hist = tmp_path / "tuning_history.jsonl"
    hist.write_text(
        json.dumps({"ts": "2026-08-01T00:00:00Z", "action": "accepted",
                    "param": "KINEMATIC_EWMA_ALPHA", "old": 0.6, "new": 0.55}) + "\n",
        encoding="utf-8")
    monkeypatch.setattr(app_module, "SAVE_PATHS", {"evaluation": str(tmp_path)})
    monkeypatch.setattr(runtime_config, "get", lambda name, default=None: default)
    with app_module.app.test_request_context("/api/local_analysis/tuning"):
        resp = app_module.api_local_analysis_tuning_get()
    data = resp.get_json() if hasattr(resp, "get_json") else json.loads(resp.data)
    assert data["last_result"]["param"] == "KINEMATIC_EWMA_ALPHA"
    assert "recent_history" not in data


def test_toggle_present_in_local_analysis_card():
    la_section = _jsx().split("Lokale Analyse am Pi", 1)[1].split("HitL", 1)[0]
    assert "toggleTuning" in la_section
    assert "Autonomes Parameter-Tuning aktiviert" in la_section


def test_tuning_status_fetched_on_mount():
    assert "/api/local_analysis/tuning" in _jsx()


def test_current_values_and_last_result_rendered():
    la_section = _jsx().split("Lokale Analyse am Pi", 1)[1].split("HitL", 1)[0]
    assert "current_values" in la_section
    assert "last_result" in la_section
    assert "recent_history" not in la_section
