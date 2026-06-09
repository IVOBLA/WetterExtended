"""P1-4: UPSCALE_FACTOR und Secret-artige Schlüssel dürfen nicht in
runtime_overrides.json gelangen."""
import pytest

pytest.importorskip("numpy")


def _rc():
    return pytest.importorskip("runtime_config")


def test_upscale_factor_forbidden():
    rc = _rc()
    assert rc.is_forbidden_override_key("UPSCALE_FACTOR")
    assert rc.forbidden_keys_in({"UPSCALE_FACTOR": 4, "SLOW_CELL_MAX_KMH": 20}) == ["UPSCALE_FACTOR"]


@pytest.mark.parametrize("key", [
    "GITHUB_TOKEN", "ANTHROPIC_API_KEY", "FOO_SECRET", "x_apikey", "MY_PRIVATE_KEY",
])
def test_secret_like_keys_forbidden(key):
    assert _rc().is_forbidden_override_key(key)


@pytest.mark.parametrize("key", [
    "SLOW_CELL_MAX_KMH", "ML_FORECAST_HORIZONS_MIN", "HAIL_WARN_THRESHOLD",
    "MIN_MOVEMENT_FOR_ARROW_KMH",
])
def test_normal_keys_allowed(key):
    assert not _rc().is_forbidden_override_key(key)


def test_patch_strips_forbidden(monkeypatch):
    rc = _rc()
    written = {}
    monkeypatch.setattr(rc, "save", lambda merged: written.update({"m": dict(merged)}))
    monkeypatch.setattr(rc, "_OVERRIDES", {}, raising=False)
    rc.patch({"UPSCALE_FACTOR": 9, "SLOW_CELL_MAX_KMH": 20})
    assert "UPSCALE_FACTOR" not in written["m"]
    assert written["m"].get("SLOW_CELL_MAX_KMH") == 20


def test_patch_strips_nested_forbidden(monkeypatch):
    rc = _rc()
    written = {}
    monkeypatch.setattr(rc, "save", lambda merged: written.update({"m": dict(merged)}))
    monkeypatch.setattr(rc, "_OVERRIDES", {}, raising=False)
    rc.patch({"AI_ANALYSIS_CONFIG": {"api_key": "sk-x"}, "SLOW_CELL_MAX_KMH": 20})
    assert "AI_ANALYSIS_CONFIG" not in written["m"]
    assert written["m"].get("SLOW_CELL_MAX_KMH") == 20


def test_api_config_rejects_forbidden_key(monkeypatch):
    app_module = pytest.importorskip("app")

    called = {"patch": False}
    monkeypatch.setattr(app_module.runtime_config, "patch", lambda data: called.update({"patch": True}))
    with app_module.app.test_request_context("/api/config", method="POST", json={"UPSCALE_FACTOR": 4}):
        response, status = app_module.api_config_save()

    assert status == 400
    assert not called["patch"]
    payload = response.get_json()
    assert payload["ok"] is False
    assert "UPSCALE_FACTOR" in payload["error"]


def test_api_config_rejects_nested_forbidden_key(monkeypatch):
    app_module = pytest.importorskip("app")

    called = {"patch": False}
    monkeypatch.setattr(app_module.runtime_config, "patch", lambda data: called.update({"patch": True}))
    with app_module.app.test_request_context(
        "/api/config", method="POST", json={"GITHUB_VERIFY_CONFIG": {"token": "secret"}}
    ):
        response, status = app_module.api_config_save()

    assert status == 400
    assert not called["patch"]
    payload = response.get_json()
    assert payload["ok"] is False
    assert "GITHUB_VERIFY_CONFIG.token" in payload["error"]


# B106: Tests für verschachtelte Secrets
def test_reject_nested_token():
    rc = _rc()
    nested = rc.forbidden_keys_in({"GITHUB_VERIFY_CONFIG": {"token": "secret"}})
    assert any("token" in p for p in nested), f"Erwartet Token-Pfad, got: {nested}"


def test_reject_deeply_nested_secret():
    rc = _rc()
    nested = rc.forbidden_keys_in({"OUTER": {"INNER": {"MY_API_KEY": "x"}}})
    assert any("MY_API_KEY" in p for p in nested)


def test_find_forbidden_paths_flat():
    rc = _rc()
    result = rc.forbidden_keys_in({"GITHUB_TOKEN": "x", "SLOW_CELL_MAX_KMH": 20})
    assert result == ["GITHUB_TOKEN"]


def test_find_forbidden_paths_mixed():
    rc = _rc()
    result = rc.forbidden_keys_in(
        {"AI_ANALYSIS_CONFIG": {"api_key": "sk-x"}, "SLOW_CELL_MAX_KMH": 20}
    )
    assert any("api_key" in p for p in result)
    assert all("SLOW_CELL_MAX_KMH" not in p for p in result)

