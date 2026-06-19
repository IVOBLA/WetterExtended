import json
import sys
import types
from pathlib import Path

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


def test_normalize_hydro_payload_tolerates_missing_values():
    raw = {"stations": [{"id": 123, "name": "Pegel A", "gewaesser": "Drau", "lon": "14,0", "lat": "46.7", "q": "1.23"}, {"name": "Ohne Werte"}]}

    normalized = hydro_fetch.normalize_hydro_payload(raw)

    assert normalized["source"] == "hydro_kaernten"
    assert normalized["raw_data_notice"] == "ungeprüfte Rohdaten / Live-Indikator"
    assert normalized["status"]["ok"] is True
    assert normalized["status"]["station_count"] == 2
    assert normalized["stations"][0]["station_id"] == "123"
    assert normalized["stations"][0]["river"] == "Drau"
    assert normalized["stations"][0]["lon"] == 14.0
    assert normalized["stations"][0]["q_m3s"] == 1.23
    assert normalized["stations"][1]["q_m3s"] is None


def test_fetch_hydro_live_success_writes_latest_and_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(hydro_fetch, "_LIVE_DIR", tmp_path)
    monkeypatch.setattr(hydro_fetch, "LATEST_FILE", tmp_path / "latest_hydro.json")
    monkeypatch.setattr(hydro_fetch, "STATUS_FILE", tmp_path / "hydro_status.json")

    class Response:
        status_code = 200
        headers = {"content-type": "application/json"}
        def json(self):
            return {"stations": [{"id": "A", "name": "A", "lat": 46.7, "lon": 14.0}]}

    calls = []
    def fake_retry_get(*args, **kwargs):
        calls.append((args, kwargs))
        return Response()

    api_calls = []
    _install_fake_http_retry(monkeypatch, fake_retry_get)
    _install_fake_debug_utils(monkeypatch, log_api_call=lambda *a, **k: api_calls.append((a, k)))

    result = hydro_fetch.fetch_hydro_live(force=True)

    assert result["status"]["ok"] is True
    assert result["status"]["from_cache"] is False
    assert len(calls) == 1
    assert api_calls
    assert (tmp_path / "latest_hydro.json").exists()
    assert (tmp_path / "hydro_status.json").exists()
    assert list(tmp_path.glob("hydro_*.json"))
