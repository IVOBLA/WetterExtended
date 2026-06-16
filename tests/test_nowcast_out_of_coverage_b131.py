"""
tests/test_nowcast_out_of_coverage_b131.py

B131: Out-of-Coverage-Gedächtnis für GeoSphere-Nowcast.
B161: auf den seit B151 gültigen Aufrufpfad umgestellt — Bulk
(assign_nowcast_to_objects) UND Einzel-Fallback (_parse_nowcast_single) laufen über
http_retry.retry_get(breaker_service="geosphere_nowcast"), NICHT mehr über rohes
requests.get. Daher wird hier http_retry.retry_get pro Test gepatcht.

OOC-Verhalten (unverändert seit B131/B151):
  - echte HTTP-4xx  -> _ooc_mark (kein Request für _OOC_TTL_S)
  - CircuitOpen/Timeout/5xx (status 0) -> KEIN _ooc_mark (transient)
  - TTL aktiv  -> Koordinate wird vor dem Request herausgefiltert (kein API-Call)
  - TTL abgelaufen -> erneuter Request
  - Erfolg -> _ooc_clear

Das Doppel-Logging (log_api_failure + log_api_call) liegt seit B151 zentral in
retry_get und wird durch tests/test_b149_retry_get_breaker.py geprüft. Der frühere
Test test_b131_single_fallback_4xx_logs_both_counter_and_failure ist damit obsolet
und entfällt.

Ausführbar: python3 -m pytest tests/test_nowcast_out_of_coverage_b131.py -v
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# B161: KEINE sys.modules.setdefault-Stubs mehr (das war die B160-Kontaminationsquelle).
# Echte Module laden; pro Test wird http_retry.retry_get via monkeypatch ersetzt.
pytest.importorskip("requests")
import http_retry  # echtes Modul (retry_get / CircuitOpenError)
import fetch_geosphere_nowcast as nowcast


_COORD = (47.128, 15.055)  # liegt INNERHALB der INCA-Bbox, GeoSphere liefert real 400


class _Resp:
    """Minimal-Antwort wie sie retry_get bei Erfolg zurückgibt."""

    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = "{}"
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._payload


def _feature(rr=0.0, ff=0.0):
    """GeoJSON-Feature im von _parse_nowcast erwarteten Format."""
    return {"properties": {"parameters": {"rr": {"data": [rr]}, "ff": {"data": [ff]}}}}


def _http_error(status):
    """Exception mit .response.status_code wie eine echte HTTPError aus retry_get."""
    exc = http_retry.requests.exceptions.HTTPError(f"http-{status}")
    exc.response = _Resp({}, status=status)
    return exc


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """OOC-Datei nach tmp lenken; echte Datei-/Log-Writes unterbinden; Cache-Miss erzwingen."""
    _path = str(tmp_path / "nowcast_out_of_coverage.json")
    monkeypatch.setattr(nowcast, "_ooc_file", lambda: _path, raising=True)
    monkeypatch.setattr(nowcast, "log_api_call", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(nowcast, "debug_log", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(nowcast, "cache_get", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(nowcast, "cache_set", lambda *a, **k: None, raising=False)
    return _path


def test_b131_4xx_marks_coordinate_out_of_coverage(monkeypatch):
    """Einzel-Fallback mit HTTP 400 -> Koordinate landet im OOC-Gedächtnis."""
    def _raise_400(url, *a, **k):
        raise _http_error(400)

    monkeypatch.setattr(http_retry, "retry_get", _raise_400)
    out = nowcast._parse_nowcast_single(_COORD)
    assert out["nowcast_rr_mm15"] == 0.0  # Default-Fallback
    assert nowcast._ooc_key(_COORD) in nowcast._ooc_load()


def test_b131_circuit_open_does_not_mark(monkeypatch):
    """CircuitOpen (status 0, transient) -> KEIN OOC-Merken."""
    def _raise_open(url, *a, **k):
        raise http_retry.CircuitOpenError("circuit open: geosphere_nowcast")

    monkeypatch.setattr(http_retry, "retry_get", _raise_open)
    out = nowcast._parse_nowcast_single(_COORD)
    assert out["nowcast_rr_mm15"] == 0.0
    assert nowcast._ooc_key(_COORD) not in nowcast._ooc_load()


def test_b131_marked_coordinate_skips_api_call(monkeypatch):
    """Gemerkte Koordinate (TTL aktiv) -> kein retry_get-Call, nur Defaults."""
    nowcast._ooc_mark(_COORD)

    def _boom(url, *a, **k):
        raise AssertionError("kein Request für gemerkte OOC-Koordinate erlaubt")

    monkeypatch.setattr(http_retry, "retry_get", _boom)
    objs = [{"id": "ooc", "lat": _COORD[0], "lon": _COORD[1]}]
    out = nowcast.assign_nowcast_to_objects(objs)
    assert out[0]["nowcast_rr_mm15"] == 0.0


def test_b131_expired_ttl_retests(monkeypatch):
    """Abgelaufene OOC-Markierung -> Koordinate wird erneut (Bulk) angefragt."""
    _d = {nowcast._ooc_key(_COORD): time.time() - (nowcast._OOC_TTL_S + 10)}
    nowcast._ooc_save(_d)

    captured = {"url": None}

    def _fake_get(url, *a, **k):
        captured["url"] = url
        return _Resp({"features": [_feature(rr=0.5, ff=5.0)]})

    monkeypatch.setattr(http_retry, "retry_get", _fake_get)
    objs = [{"id": "retest", "lat": _COORD[0], "lon": _COORD[1]}]
    out = nowcast.assign_nowcast_to_objects(objs)
    assert captured["url"] is not None  # Re-Test fand statt (TTL abgelaufen)
    assert out[0]["nowcast_rr_mm15"] == 0.5


def test_b131_success_clears_out_of_coverage(monkeypatch):
    """Erfolgreicher Einzel-Abruf hebt eine bestehende OOC-Markierung auf."""
    nowcast._ooc_mark(_COORD)
    assert nowcast._ooc_key(_COORD) in nowcast._ooc_load()

    def _ok(url, *a, **k):
        return _Resp({"features": [_feature(rr=1.0, ff=3.0)]})

    monkeypatch.setattr(http_retry, "retry_get", _ok)
    nowcast._parse_nowcast_single(_COORD)
    assert nowcast._ooc_key(_COORD) not in nowcast._ooc_load()
