"""P109 — Admin-Panel zeigt Default-Werte neben aktuellen Tuning-Werten."""
from pathlib import Path

import pytest

pytest.importorskip("flask")

import app as app_module
import config
import runtime_config

REPO = Path(__file__).resolve().parents[1]
JSX = REPO / "frontend" / "src" / "pages" / "AiSuggestions.jsx"


def _get_tuning_payload(monkeypatch, tmp_path, runtime_overrides=None):
    # B508: /api/local_analysis/tuning erfordert eine authentifizierte Session.
    import auth as auth_module

    user = {"role": "admin", "sub": "1"}
    monkeypatch.setattr(app_module, "get_current_user", lambda: user)
    monkeypatch.setattr(auth_module, "get_current_user", lambda: user)

    eval_dir = tmp_path / "evaluation"
    eval_dir.mkdir()
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


def test_default_values_complete_and_equal_config_defaults_despite_runtime_overrides(monkeypatch, tmp_path):
    first_param = next(iter(config.AUTONOMOUS_TUNING_PARAMS))
    runtime_override = getattr(config, first_param) + 1

    data = _get_tuning_payload(
        monkeypatch,
        tmp_path,
        runtime_overrides={first_param: runtime_override},
    )

    assert set(data["default_values"]) == set(config.AUTONOMOUS_TUNING_PARAMS)
    for name in config.AUTONOMOUS_TUNING_PARAMS:
        assert data["default_values"][name] == getattr(config, name)


def test_current_value_override_differs_from_unchanged_default_value(monkeypatch, tmp_path):
    first_param = next(iter(config.AUTONOMOUS_TUNING_PARAMS))
    config_default = getattr(config, first_param)
    runtime_override = config_default + 1

    data = _get_tuning_payload(
        monkeypatch,
        tmp_path,
        runtime_overrides={first_param: runtime_override},
    )

    assert data["current_values"][first_param] == runtime_override
    assert data["default_values"][first_param] == config_default
    assert data["current_values"][first_param] != data["default_values"][first_param]


def test_frontend_uses_tuning_default_values_for_default_hint():
    source = JSX.read_text(encoding="utf-8")

    assert "tuning.default_values" in source
    assert "Default:" in source
