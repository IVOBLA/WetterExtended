"""
B313: Watchdog-Haertung fuer fetch_outlook_series(). Ein haengender/langsamer
Open-Meteo-Endpoint darf den Gesamtlauf nicht ueber OUTLOOK_SERIES_MAX_WALLTIME_S
hinaus blockieren, und retry_get() wird mit max_retries=1 statt Default 2 genutzt.
"""
import sys
import time
import types

import pytest


class _StubHTTPError(Exception):
    def __init__(self, *args, response=None, **kwargs):
        super().__init__(*args)
        self.response = response


class _StubResponse:
    def __init__(self):
        self.status_code = 200
        self.headers = {}


# Einige Legacy-Outlook-Tests verwenden requests-Stubs. Fuer diesen isolierten
# B313-Test stellen wir sicher, dass fetch_outlook_series auch ohne installiertes
# requests-Paket mit den benoetigten Exception-Klassen importierbar ist.
_requests_stub = types.SimpleNamespace(
    Response=_StubResponse,
    exceptions=types.SimpleNamespace(
        HTTPError=_StubHTTPError,
        Timeout=TimeoutError,
        SSLError=OSError,
        ConnectionError=ConnectionError,
        RequestException=Exception,
    ),
)
_existing_requests = sys.modules.get("requests")
if (
    _existing_requests is None
    or not hasattr(_existing_requests, "exceptions")
    or not hasattr(_existing_requests.exceptions, "ConnectionError")
    or not hasattr(_existing_requests, "Response")
):
    sys.modules["requests"] = _requests_stub

# http_retry importiert normalerweise requests.adapters. In der schlanken
# Testumgebung reicht fuer B313 ein Stub, weil nur die weitergereichten kwargs
# verifiziert werden.
sys.modules.setdefault("http_retry", types.SimpleNamespace(retry_get=lambda *a, **k: None))

fos = pytest.importorskip("fetch_outlook_series")


def test_max_walltime_constant_is_well_under_watchdog_default():
    # WatchdogSec-Default ist 60s; das Budget muss deutlich darunter liegen.
    assert fos.OUTLOOK_SERIES_MAX_WALLTIME_S < 40


def test_request_uses_max_retries_one(monkeypatch):
    captured = {}

    def _fake_retry_get(url, **kwargs):
        captured.update(kwargs)
        raise fos.requests.exceptions.ConnectionError("simulated hang")

    monkeypatch.setattr("http_retry.retry_get", _fake_retry_get)
    try:
        fos._request([46.6], [14.3], fos._HOURLY_FULL)
    except Exception:
        pass
    assert captured.get("max_retries") == 1


def test_fetch_series_aborts_within_walltime_budget(monkeypatch):
    # Simuliert einen Endpoint, der bei jedem Versuch haengt (ConnectionError nach
    # kurzer, aber wiederholbarer Verzoegerung). Der Gesamtlauf darf trotzdem nicht
    # laenger als OUTLOOK_SERIES_MAX_WALLTIME_S + eine kleine Toleranz dauern.
    monkeypatch.setattr(fos.api_circuit_breaker, "is_open", lambda *_a, **_k: False)
    monkeypatch.setattr(fos.api_circuit_breaker, "record_failure", lambda *_a, **_k: None)
    monkeypatch.setattr(fos.api_circuit_breaker, "record_success", lambda *_a, **_k: None)
    monkeypatch.setattr(fos, "_is_fresh", lambda: False)
    monkeypatch.setattr(fos, "MAX_REQUESTS_PER_RUN", 999)
    monkeypatch.setattr(fos, "OUTLOOK_SERIES_MAX_WALLTIME_S", 2.0)

    def _slow_request(lats, lons, hourly):
        time.sleep(0.5)
        raise fos.requests.exceptions.ConnectionError("simulated hang")

    monkeypatch.setattr(fos, "_request", _slow_request)
    monkeypatch.setattr(fos, "ATM_SNAPSHOT_LOCATIONS", [{"lat": 46.6, "lon": 14.3, "name": f"p{i}"} for i in range(40)])

    t0 = time.monotonic()
    fos.fetch_outlook_series(force=True)
    elapsed = time.monotonic() - t0
    assert elapsed < 2.0 + 2.0, f"Lauf dauerte {elapsed:.1f}s, erwartet < ~4s bei Budget=2s"
