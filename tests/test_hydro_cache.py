import json
import sys
import types
import os
import time

import hydro_fetch




def _install_fake_debug_utils(monkeypatch, *, log_api_call=None, log_api_failure=None):
    module = types.SimpleNamespace(
        log_api_call=log_api_call or (lambda *a, **k: None),
        log_api_failure=log_api_failure or (lambda *a, **k: None),
        debug_log=lambda *a, **k: None,
    )
    monkeypatch.setitem(sys.modules, "debug_utils", module)

def _install_fake_http_retry(monkeypatch, func):
    module = types.SimpleNamespace(retry_get=func)
    monkeypatch.setitem(sys.modules, "http_retry", module)


def _patch_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(hydro_fetch, "_LIVE_DIR", tmp_path)
    monkeypatch.setattr(hydro_fetch, "LATEST_FILE", tmp_path / "latest_hydro.json")
    monkeypatch.setattr(hydro_fetch, "STATUS_FILE", tmp_path / "hydro_status.json")


def test_repeated_calls_inside_ttl_do_not_request(tmp_path, monkeypatch):
    _patch_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(hydro_fetch, "DEFAULT_TTL_SECONDS", 600)
    cached = hydro_fetch.normalize_hydro_payload({"stations": [{"id": "C"}]})
    hydro_fetch.LATEST_FILE.write_text(json.dumps(cached), encoding="utf-8")

    def fail_retry_get(*args, **kwargs):
        raise AssertionError("should not request inside TTL")

    _install_fake_http_retry(monkeypatch, fail_retry_get)

    result = hydro_fetch.fetch_hydro_live()

    assert result["status"]["from_cache"] is True
    assert result["status"]["ok"] is True
    assert result["status"]["station_count"] == 1


def test_error_uses_stale_cache(tmp_path, monkeypatch):
    _patch_paths(tmp_path, monkeypatch)
    cached = hydro_fetch.normalize_hydro_payload({"stations": [{"id": "OLD"}]})
    hydro_fetch.LATEST_FILE.write_text(json.dumps(cached), encoding="utf-8")
    old = time.time() - 3600
    os.utime(hydro_fetch.LATEST_FILE, (old, old))

    _install_fake_http_retry(monkeypatch, lambda *a, **k: (_ for _ in ()).throw(TimeoutError("offline")))
    failures = []
    _install_fake_debug_utils(monkeypatch, log_api_failure=lambda *a, **k: failures.append((a, k)))

    result = hydro_fetch.fetch_hydro_live()

    assert result["stations"][0]["station_id"] == "OLD"
    assert result["status"]["ok"] is False
    assert result["status"]["from_cache"] is True
    assert "TimeoutError" in result["status"]["last_error"]
    assert failures


def test_load_latest_hydro_live_respects_max_age(tmp_path, monkeypatch):
    _patch_paths(tmp_path, monkeypatch)
    hydro_fetch.LATEST_FILE.write_text(json.dumps({"status": {}}), encoding="utf-8")
    old = time.time() - 100
    os.utime(hydro_fetch.LATEST_FILE, (old, old))

    assert hydro_fetch.load_latest_hydro_live(max_age_seconds=10) is None
    assert hydro_fetch.load_latest_hydro_live(max_age_seconds=200) is not None
