import os
import types

import pytest
from flask import Flask


@pytest.fixture
def client(monkeypatch):
    import app as app_module
    import auth

    app_module.app.config.update(TESTING=True)
    monkeypatch.setattr(auth, "get_current_user", lambda: {"role": "admin"})
    return app_module.app.test_client()


def _assert_contract(resp, expected_code=200):
    assert resp.status_code == expected_code
    assert resp.is_json
    payload = resp.get_json()
    assert "ok" in payload
    assert "status" in payload
    assert ("data" in payload) ^ ("error" in payload)
    return payload


def test_flask_test_client_available():
    app = Flask(__name__)
    assert app.test_client() is not None


def test_all_hydro_get_endpoints_return_stable_json(client, monkeypatch):
    hydro_api = types.SimpleNamespace(
        status=lambda: {"status": "ok", "station_count": 1},
        station_features=lambda include_disabled=False, map_view=False: {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "properties": {"station_id": "S1"}}],
        },
        catchments_all=lambda: {"features": [{"type": "Feature", "properties": {"station_id": "S1"}}]},
        normalized_impacts=lambda latest=False: [{"station_id": "S1", "score": 0.7}],
    )
    hydro_fetch = types.SimpleNamespace(
        load_latest_hydro_live=lambda max_age_seconds=None: {"status": "ok", "stations": [{"station_id": "S1"}]}
    )
    hydro_verification = types.SimpleNamespace(
        get_hydro_verification_summary=lambda: {"status": "ok", "pending": 0}
    )
    monkeypatch.setitem(__import__("sys").modules, "hydro_api", hydro_api)
    monkeypatch.setitem(__import__("sys").modules, "hydro_fetch", hydro_fetch)
    monkeypatch.setitem(__import__("sys").modules, "hydro_verification", hydro_verification)

    for path in (
        "/api/hydro/status",
        "/api/hydro/live",
        "/api/hydro/stations",
        "/api/hydro/catchments",
        "/api/hydro/impacts",
        "/api/hydro/verification",
    ):
        payload = _assert_contract(client.get(path))
        assert payload["ok"] is True


def test_hydro_no_data_and_disabled_return_json_without_500(client, monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "hydro_api", types.SimpleNamespace(
        status=lambda: {"status": "hydro_disabled", "enabled": False, "station_count": 0},
        station_features=lambda include_disabled=False, map_view=False: {"status": "no_hydro_data", "type": "FeatureCollection", "features": []},
        catchments_all=lambda: {"status": "no_hydro_data", "features": []},
        normalized_impacts=lambda latest=False: [],
    ))
    monkeypatch.setitem(__import__("sys").modules, "hydro_fetch", types.SimpleNamespace(
        load_latest_hydro_live=lambda max_age_seconds=None: None
    ))
    monkeypatch.setitem(__import__("sys").modules, "hydro_verification", types.SimpleNamespace(
        get_hydro_verification_summary=lambda: {"status": "hydro_disabled", "enabled": False}
    ))

    for path in ("/api/hydro/status", "/api/hydro/live", "/api/hydro/stations", "/api/hydro/catchments", "/api/hydro/impacts", "/api/hydro/verification"):
        _assert_contract(client.get(path))


def test_hydro_expected_error_cases_return_json_without_500(client, monkeypatch):
    def boom(message):
        raise RuntimeError(message)

    monkeypatch.setitem(__import__("sys").modules, "hydro_api", types.SimpleNamespace(
        status=lambda: boom("missing static data"),
        station_features=lambda include_disabled=False, map_view=False: boom("invalid static data"),
        catchments_all=lambda: boom("invalid static data"),
        normalized_impacts=lambda latest=False: boom("missing hydro data"),
    ))
    monkeypatch.setitem(__import__("sys").modules, "hydro_fetch", types.SimpleNamespace(
        load_latest_hydro_live=lambda max_age_seconds=None: boom("live hydro unreachable")
    ))
    monkeypatch.setitem(__import__("sys").modules, "hydro_verification", types.SimpleNamespace(
        get_hydro_verification_summary=lambda: boom("invalid static data")
    ))

    for path in ("/api/hydro/status", "/api/hydro/live", "/api/hydro/stations", "/api/hydro/catchments", "/api/hydro/impacts", "/api/hydro/verification"):
        payload = _assert_contract(client.get(path))
        assert payload["ok"] is False
        assert payload["status"].startswith("hydro_")


def test_hydro_admin_endpoints_are_active_mocked_and_json(client, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setitem(__import__("sys").modules, "hydro_static_import", types.SimpleNamespace(
        build_static_hydro=lambda static_dir=None: calls.append("static") or {"status": "ok", "stations": 1},
        run_build_job=lambda static_dir=None: calls.append("static") or {"status": "ok", "stations": 1},
        _write_hydro_job_state=lambda static_dir, state: calls.append("job"),
    ))
    import app as _app_mod, hydro_api
    monkeypatch.setattr(hydro_api, "STATIC_GENERATED", tmp_path)
    monkeypatch.setattr(_app_mod.subprocess, "Popen", lambda *a, **k: types.SimpleNamespace(pid=os.getpid()))
    monkeypatch.setitem(__import__("sys").modules, "hydro_fetch", types.SimpleNamespace(
        fetch_hydro_live=lambda force=True: calls.append(("live", force)) or {"status": "ok", "stations": []}
    ))
    monkeypatch.setitem(__import__("sys").modules, "hydro_verification", types.SimpleNamespace(
        verify_pending_hydro_impacts=lambda: calls.append("verify") or []
    ))
    import runtime_config
    monkeypatch.setattr(runtime_config, "get", lambda key, default=None: {}, raising=False)
    monkeypatch.setattr(runtime_config, "patch", lambda patch: calls.append(("patch", patch)), raising=False)

    for method, path, kwargs in (
        (client.post, "/api/admin/hydro/reload-static", {}),
        (client.post, "/api/admin/hydro/fetch-live", {}),
        (client.post, "/api/admin/hydro/verify", {}),
        (client.patch, "/api/admin/hydro/stations/S1", {"json": {"enabled": False}}),
    ):
        payload = _assert_contract(method(path, **kwargs))
        assert payload["ok"] is True
    assert calls


def test_hydro_admin_endpoints_respect_admin_auth(client, monkeypatch):
    import auth
    monkeypatch.setattr(auth, "get_current_user", lambda: {"role": "operator"})
    for method, path in (
        (client.post, "/api/admin/hydro/reload-static"),
        (client.post, "/api/admin/hydro/fetch-live"),
        (client.post, "/api/admin/hydro/verify"),
        (client.patch, "/api/admin/hydro/stations/S1"),
    ):
        payload = _assert_contract(method(path, json={"enabled": False}), 403)
        assert payload["ok"] is False
