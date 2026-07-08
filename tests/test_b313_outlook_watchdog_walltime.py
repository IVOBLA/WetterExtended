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
_needed_requests_stub = (
    _existing_requests is None
    or not hasattr(_existing_requests, "exceptions")
    or not hasattr(_existing_requests.exceptions, "ConnectionError")
    or not hasattr(_existing_requests, "Response")
)
if _needed_requests_stub:
    sys.modules["requests"] = _requests_stub

# http_retry importiert normalerweise requests.adapters. In der schlanken
# Testumgebung reicht fuer B313 ein Stub, weil nur die weitergereichten kwargs
# verifiziert werden.
_existing_http_retry = sys.modules.get("http_retry")
_needed_http_retry_stub = _existing_http_retry is None
if _needed_http_retry_stub:
    sys.modules["http_retry"] = types.SimpleNamespace(retry_get=lambda *a, **k: None)

fos = pytest.importorskip("fetch_outlook_series")

# B318: Falls requests nur fuer den fetch_outlook_series-Import gestubbt wurde,
# darf der Stub nicht schon waehrend der Collection nachfolgender Testmodule in
# sys.modules sichtbar bleiben. Sonst wuerde z. B. pytest.importorskip("requests")
# in test_b149_retry_get_breaker.py faelschlich nicht skippen, obwohl das echte
# Paket in der schlanken Umgebung fehlt. fetch_outlook_series haelt seine
# Modulreferenz bereits in fos.requests.
if _needed_requests_stub and _existing_requests is None:
    sys.modules.pop("requests", None)


@pytest.fixture(autouse=True, scope="module")
def _restore_stubbed_modules():
    """B318: Stellt sys.modules['requests']/['http_retry'] nach diesem Testmodul
    wieder her, falls oben ein Stub installiert wurde. Ohne dieses Teardown bleibt
    der Stub fuer den Rest der pytest-Session aktiv und laesst andere Testdateien
    (z. B. test_b149_retry_get_breaker.py, das http_retry._SESSION braucht) je
    nach Sammel-/Ausfuehrungsreihenfolge fehlschlagen."""
    yield
    if _needed_http_retry_stub:
        if _existing_http_retry is None:
            sys.modules.pop("http_retry", None)
        else:
            sys.modules["http_retry"] = _existing_http_retry
    if _needed_requests_stub:
        if _existing_requests is None:
            sys.modules.pop("requests", None)
        else:
            sys.modules["requests"] = _existing_requests


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
    # B320: fos.log_api_failure DIREKT patchen (nicht debug_utils._API_HEALTH_FILE
    # oder debug_utils.log_api_failure). fetch_outlook_series.py bindet
    # log_api_failure per "from debug_utils import log_api_failure" EINMALIG beim
    # eigenen Modulimport. Wird debug_utils irgendwo in der Gesamt-Suite neu geladen
    # (sys.modules.pop + reimport, z. B. via conftest._ensure_real_debug_utils()),
    # zeigt diese bereits gebundene Referenz weiter auf das ALTE Modul-Dict — ein
    # Patch auf debug_utils selbst hat dann keine Wirkung mehr und synthetische
    # Testeintraege ("simulated hang") landen in der ECHTEN
    # train_data/evaluation/api_health.jsonl (verifiziert im 24h-Debug-Export vom
    # 2026-07-07, Zeitstempel 08:27:34-36Z). Empirisch mit dem vollen 1442-Test-Lauf
    # verifiziert: mit diesem Patch bleibt die echte Datei unberuehrt.
    monkeypatch.setattr(fos, "log_api_failure", lambda *a, **k: None)
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
