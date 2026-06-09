"""P1-1: Öffentliche GETs bleiben offen, sensible GETs erfordern Login."""
import pytest

pytest.importorskip("flask")


def _client():
    app_mod = pytest.importorskip("app")
    app_mod.app.config["TESTING"] = True
    return app_mod.app.test_client()


def test_public_get_not_blocked():
    c = _client()
    # /api/objects ist öffentlich → darf NICHT 401/403 sein
    r = c.get("/api/objects")
    assert r.status_code not in (401, 403), f"/api/objects -> {r.status_code}"


@pytest.mark.parametrize("path", [
    "/api/config",
    "/api/logs",
    "/api/email_config",
    "/api/notification",
    "/api/users",
])
def test_sensitive_get_requires_auth(path):
    c = _client()
    r = c.get(path)
    assert r.status_code in (401, 403), f"{path} ungeschützt -> {r.status_code}"
