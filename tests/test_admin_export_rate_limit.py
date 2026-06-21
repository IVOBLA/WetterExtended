"""Regressionen fuer Admin-Debug-Export bei nginx-429 auf Status-Polls."""
from pathlib import Path
import time

import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    pytest.importorskip("flask")
    import app as app_module
    monkeypatch.setitem(app_module.SAVE_PATHS, "objects", str(tmp_path / "objects"))
    monkeypatch.setitem(app_module.SAVE_PATHS, "evaluation", str(tmp_path / "evaluation"))
    (tmp_path / "objects").mkdir()
    (tmp_path / "evaluation").mkdir()
    app_module.app.config.update(TESTING=True, DEBUG_EXPORT_BASE_DIR=str(tmp_path))
    app_module._EXPORT_BUILDS.clear()
    return app_module.app.test_client()


def _login(monkeypatch, user):
    """B223: Der before_request-Gate (_jwt_auth_check) nutzt auth.get_current_user,
    der Endpoint-Body app.get_current_user — beide müssen gepatcht werden."""
    import app as app_module
    import auth as auth_module
    monkeypatch.setattr(app_module, "get_current_user", lambda: user)
    monkeypatch.setattr(auth_module, "get_current_user", lambda: user)


def test_frontend_status_429_is_retryable_with_backoff():
    src = Path("frontend/src/pages/Logs.jsx").read_text(encoding="utf-8")
    assert "EXPORT_STATUS_POLL_MIN_MS = 3000" in src
    assert "function isRateLimitError" in src
    assert "error?.status === 429" in src
    assert "nextExportBackoffMs" in src
    assert "Server ausgelastet / Rate-Limit, versuche erneut" in src
    rate_limit_block = src[src.index("catch (e) {"):src.index("if (Date.now() > deadline)")]
    assert "if (!isRateLimitError(e)) throw e" in rate_limit_block
    assert "pollDelayMs = nextExportBackoffMs(pollDelayMs)" in rate_limit_block
    assert "Datenexport fehlgeschlagen" not in rate_limit_block


def test_frontend_non_retryable_status_errors_remain_final_failures():
    src = Path("frontend/src/pages/Logs.jsx").read_text(encoding="utf-8")
    assert "if (!isRateLimitError(e)) throw e" in src
    assert "throw new Error(`Export-Build fehlgeschlagen" in src
    assert "Datenexport fehlgeschlagen" in src


def test_frontend_export_pauses_parallel_logs_and_job_status_polls():
    src = Path("frontend/src/pages/Logs.jsx").read_text(encoding="utf-8")
    assert "if (exportingRef.current) return" in src
    assert "<ManualFetchPanel paused={exporting} />" in src
    assert "if (paused) return Promise.resolve()" in src
    assert "paused ? 30000" in src


def test_api_errors_keep_http_status_for_429_detection():
    src = Path("frontend/src/api.js").read_text(encoding="utf-8")
    assert "e.status = r.status" in src
    assert "e.url = url" in src


def test_nginx_export_endpoints_not_in_wetter_api_limit_location():
    src = Path("install.sh").read_text(encoding="utf-8")
    assert "zone=wetter_admin_export" in src
    export_loc_start = src.index("location ~ ^/api/admin/export/")
    export_loc_end = src.index("    # Logs/Admin-Liveansicht", export_loc_start)
    export_block = src[export_loc_start:export_loc_end]
    assert "last-24h/parts" in export_block
    assert "status" in export_block
    assert "download" in export_block
    assert "part" in export_block
    assert "limit_req zone=wetter_admin_export" in export_block
    assert "limit_req zone=wetter_api" not in export_block
    api_loc_start = src.index("location /api/ {")
    api_block = src[api_loc_start:src.index("    # Auth-Endpunkte", api_loc_start)]
    assert "limit_req zone=wetter_api" in api_block


def test_status_endpoint_is_lightweight_for_existing_token(client, monkeypatch):
    import app as app_module
    from pathlib import Path as P

    user = {"role": "admin", "sub": "1"}
    _login(monkeypatch, user)
    token = "building-token"
    app_module._EXPORT_BUILDS.clear()

    class BuildingProc:
        def poll(self):
            return None

    app_module._EXPORT_BUILDS[token] = {
        "dir": P("/tmp/unused"), "proc": BuildingProc(), "log_fh": None,
        "status": "building", "parts": None, "manifest": None,
        "detail": None, "created": time.time(),
    }
    started = time.perf_counter()
    resp = client.get(f"/api/admin/export/status?token={token}")
    elapsed = time.perf_counter() - started
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "building"}
    assert elapsed < 0.2


def test_status_500_remains_real_error(client, monkeypatch):
    import app as app_module
    from pathlib import Path as P

    user = {"role": "admin", "sub": "1"}
    _login(monkeypatch, user)
    token = "error-token"
    app_module._EXPORT_BUILDS.clear()
    app_module._EXPORT_BUILDS[token] = {
        "dir": P("/tmp/unused"), "proc": None, "log_fh": None,
        "status": "error", "parts": None, "manifest": None,
        "detail": "boom", "created": time.time(),
    }
    resp = client.get(f"/api/admin/export/status?token={token}")
    assert resp.status_code == 500
    assert resp.get_json()["status"] == "error"


def test_status_auth_and_unknown_token_errors(client, monkeypatch):
    import app as app_module
    _login(monkeypatch, None)
    assert client.get("/api/admin/export/status?token=x").status_code == 401

    _login(monkeypatch, {"role": "viewer", "sub": "1"})
    assert client.get("/api/admin/export/status?token=x").status_code == 403

    _login(monkeypatch, {"role": "admin", "sub": "1"})
    app_module._EXPORT_BUILDS.clear()
    assert client.get("/api/admin/export/status?token=missing").status_code == 410
