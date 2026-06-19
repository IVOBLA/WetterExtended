import json
import sys
import types

import hydro_fetch
from external_response_logger import normalize_source




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


def test_external_logger_normalizes_hydro_category():
    assert normalize_source("hydro_kaernten") == "hydro"


def test_failed_fetch_is_visible_in_health_log(tmp_path, monkeypatch):
    monkeypatch.setattr(hydro_fetch, "_LIVE_DIR", tmp_path / "live")
    monkeypatch.setattr(hydro_fetch, "LATEST_FILE", tmp_path / "live" / "latest_hydro.json")
    monkeypatch.setattr(hydro_fetch, "STATUS_FILE", tmp_path / "live" / "hydro_status.json")

    _install_fake_http_retry(monkeypatch, lambda *a, **k: (_ for _ in ()).throw(ValueError("bad json")))
    failures = []
    _install_fake_debug_utils(monkeypatch, log_api_failure=lambda service, url, reason, **kwargs: failures.append({"service": service, "url": url, "reason": reason, **kwargs}))

    result = hydro_fetch.fetch_hydro_live(force=True)

    assert result["status"]["ok"] is False
    assert result["status"]["from_cache"] is False
    assert failures
    assert failures[0]["service"] == "hydro_kaernten"
    assert failures[0]["fallback_used"] is False
    status = json.loads((tmp_path / "live" / "hydro_status.json").read_text(encoding="utf-8"))
    assert status["ok"] is False
    assert "bad json" in status["last_error"]
