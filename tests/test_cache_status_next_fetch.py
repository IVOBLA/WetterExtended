"""B125: /api/cache_status liefert absolute next_fetch_ts."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    pytest.importorskip("flask")
    import app as app_module
    import api_cache

    # Cache-Verzeichnis mit einer frischen Datei bestücken
    cache_dir = tmp_path / "api_cache"
    cache_dir.mkdir()
    monkeypatch.setattr(api_cache, "_CACHE_DIR", str(cache_dir))
    f = cache_dir / "blitzortung_last_strikes_abc.json"
    f.write_text("{}", encoding="utf-8")
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client(), f


def test_next_fetch_ts_present_and_after_last(client):
    c, _ = client
    r = c.get("/api/cache_status")
    assert r.status_code == 200
    services = r.get_json()["services"]
    # mindestens ein Service mit gesetztem next_fetch_ts und ttl
    withttl = [s for s in services if s.get("ttl_s") and s.get("next_fetch_ts")]
    assert withttl, "kein Service mit next_fetch_ts"
    for s in withttl:
        if s["last_fetch_ts"]:
            assert s["next_fetch_ts"] > s["last_fetch_ts"], (
                "next_fetch_ts muss nach last_fetch_ts liegen"
            )


def test_missing_service_has_no_next_fetch(client):
    c, _ = client
    services = c.get("/api/cache_status").get_json()["services"]
    for s in services:
        if s["status"] == "MISSING":
            assert s["next_fetch_ts"] is None
