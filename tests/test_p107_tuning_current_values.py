"""P107 — Admin-Panel zeigt aktuelle Tuning-Werte und genau letztes Ergebnis."""
import json
from pathlib import Path

import pytest

pytest.importorskip("flask")

import app as app_module
import config
import runtime_config

REPO = Path(__file__).resolve().parents[1]
JSX = REPO / "frontend" / "src" / "pages" / "AiSuggestions.jsx"


def _get_tuning_payload(monkeypatch, tmp_path, runtime_overrides=None, history_lines=None):
    # B508: /api/local_analysis/tuning erfordert eine authentifizierte Session
    # (app.py::before_request prueft auth.get_current_user()). Beide Modul-
    # Referenzen patchen, exakt wie in tests/test_b351_config_save_value_error.py.
    import auth as auth_module
    user = {"role": "admin", "sub": "1"}
    monkeypatch.setattr(app_module, "get_current_user", lambda: user)
    monkeypatch.setattr(auth_module, "get_current_user", lambda: user)

    eval_dir = tmp_path / "evaluation"
    eval_dir.mkdir(parents=True, exist_ok=True)
    if history_lines is not None:
        (eval_dir / "tuning_history.jsonl").write_text(
            "\n".join(json.dumps(item) for item in history_lines) + ("\n" if history_lines else ""),
            encoding="utf-8",
        )
    monkeypatch.setattr(app_module, "SAVE_PATHS", {"evaluation": str(eval_dir)})
    runtime_overrides = dict(runtime_overrides or {})
    monkeypatch.setattr(
        runtime_config,
        "get",
        lambda name, default=None: runtime_overrides.get(name, default),
    )
    with app_module.app.test_client() as client:
        response = client.get("/api/local_analysis/tuning")
    assert response.status_code == 200
    return response.get_json()


def test_current_values_complete_and_last_result_from_history(monkeypatch, tmp_path):
    first_param = next(iter(config.AUTONOMOUS_TUNING_PARAMS))
    history = [
        {"ts": "2026-08-01T00:00:00Z", "action": "plateau", "parameter": first_param},
        {
            "ts": "2026-08-01T00:05:00Z",
            "action": "improved",
            "parameter": first_param,
            "old_value": getattr(config, first_param),
            "candidate_value": 123,
        },
    ]

    data = _get_tuning_payload(
        monkeypatch,
        tmp_path,
        runtime_overrides={first_param: 123},
        history_lines=history,
    )

    assert set(data["current_values"]) == set(config.AUTONOMOUS_TUNING_PARAMS)
    assert data["current_values"][first_param] == 123
    assert data["last_result"] == history[-1]
    assert "recent_history" not in data


def test_current_values_falls_back_to_config_default(monkeypatch, tmp_path):
    first_param = next(iter(config.AUTONOMOUS_TUNING_PARAMS))

    data = _get_tuning_payload(monkeypatch, tmp_path)

    assert data["current_values"][first_param] == getattr(config, first_param)
    assert data["current_values"][first_param] is not None


def test_last_result_is_none_for_empty_or_missing_history(monkeypatch, tmp_path):
    missing_data = _get_tuning_payload(monkeypatch, tmp_path)
    assert missing_data["last_result"] is None

    empty_data = _get_tuning_payload(monkeypatch, tmp_path / "empty", history_lines=[])
    assert empty_data["last_result"] is None


def test_frontend_shows_current_values_and_last_result_labels_only():
    source = JSX.read_text(encoding="utf-8")

    assert "Aktuell getunte Werte" in source
    assert "Letztes Ergebnis" in source
    assert "Letzte Tuning-Aktionen" not in source
