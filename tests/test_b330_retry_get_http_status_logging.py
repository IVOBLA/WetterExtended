"""B330: retry_get() protokolliert nach Retry-Erschoepfung bei einem echten
HTTP-5xx den tatsaechlichen Statuscode statt http=None."""

import importlib
import sys
import types

import pytest


class _FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code
        self.headers = {}
        self.text = "Bad Gateway"

    def raise_for_status(self):
        requests = sys.modules["requests"]
        err = requests.exceptions.HTTPError(f"{self.status_code} Error")
        err.response = self
        raise err


def _import_http_retry_with_fake_requests(monkeypatch):
    """Importiert http_retry mit minimalem requests/urllib3-Stub.

    Die Testumgebung enthaelt nicht zwingend requests. Fuer B330 wird nur das
    Exception-/Session-Verhalten benoetigt, daher reicht ein kleiner Stub.
    """

    class RequestException(Exception):
        pass

    class HTTPError(RequestException):
        pass

    class Timeout(RequestException):
        pass

    class SSLError(RequestException):
        pass

    class ConnectionError(RequestException):
        pass

    class _Session:
        def __init__(self):
            self.headers = {}

        def mount(self, *args, **kwargs):
            return None

        def get(self, *args, **kwargs):
            raise AssertionError("Session.get muss im Test gemonkeypatcht werden")

    class _HTTPAdapter:
        def __init__(self, *args, **kwargs):
            pass

    class _Retry:
        def __init__(self, *args, **kwargs):
            pass

    class Response:
        """Platzhalter — http_retry.py referenziert requests.Response nur als
        Typ-Annotation (`-> requests.Response`), die beim Modul-Import sofort
        ausgewertet wird. Ohne dieses Attribut schlaegt der Reimport unten mit
        AttributeError fehl."""

    requests_mod = types.ModuleType("requests")
    exceptions_mod = types.SimpleNamespace(
        RequestException=RequestException,
        HTTPError=HTTPError,
        Timeout=Timeout,
        SSLError=SSLError,
        ConnectionError=ConnectionError,
    )
    requests_mod.exceptions = exceptions_mod
    requests_mod.Session = _Session
    requests_mod.Response = Response

    adapters_mod = types.ModuleType("requests.adapters")
    adapters_mod.HTTPAdapter = _HTTPAdapter

    urllib3_mod = types.ModuleType("urllib3")
    urllib3_util_mod = types.ModuleType("urllib3.util")
    urllib3_retry_mod = types.ModuleType("urllib3.util.retry")
    urllib3_retry_mod.Retry = _Retry
    urllib3_util_mod.Retry = _Retry

    monkeypatch.setitem(sys.modules, "requests", requests_mod)
    monkeypatch.setitem(sys.modules, "requests.adapters", adapters_mod)
    monkeypatch.setitem(sys.modules, "urllib3", urllib3_mod)
    monkeypatch.setitem(sys.modules, "urllib3.util", urllib3_util_mod)
    monkeypatch.setitem(sys.modules, "urllib3.util.retry", urllib3_retry_mod)
    # B338-Fix: monkeypatch.delitem statt rohem sys.modules.pop() — stellt den
    # urspruenglichen Zustand von sys.modules["http_retry"] beim Test-Teardown
    # garantiert wieder her, auch wenn der folgende Reimport fehlschlaegt.
    monkeypatch.delitem(sys.modules, "http_retry", raising=False)
    return importlib.import_module("http_retry"), requests_mod


def test_5xx_erschoepfung_loggt_echten_status(monkeypatch):
    hr, requests_mod = _import_http_retry_with_fake_requests(monkeypatch)

    captured = {}

    def _fake_log_api_failure(service, url, reason, fallback_used=False, http_status=None):
        captured["service"] = service
        captured["http_status"] = http_status
        captured["fallback_used"] = fallback_used

    monkeypatch.setattr(hr, "log_api_failure", _fake_log_api_failure)
    monkeypatch.setattr(hr, "log_api_call", lambda *a, **k: None)
    monkeypatch.setattr(hr.time, "sleep", lambda *_: None)

    def _fake_get(url, timeout, **kwargs):
        return _FakeResponse(502)

    monkeypatch.setattr(hr._SESSION, "get", _fake_get)

    with pytest.raises(requests_mod.exceptions.HTTPError):
        hr.retry_get(
            "https://api.open-meteo.com/v1/forecast",
            service="Open-Meteo-Outlook",
            max_retries=2,
            backoff=[0, 0],
        )

    assert captured["http_status"] == 502, (
        "Nach Retry-Erschoepfung muss der echte HTTP-Statuscode (502) an "
        "log_api_failure() uebergeben werden, nicht None."
    )
    assert captured["fallback_used"] is True


def test_timeout_erschoepfung_loggt_weiterhin_none(monkeypatch):
    """Regression: Bei einem reinen Timeout (kein HTTPError) bleibt
    http_status=None — das ist korrekt, da kein Statuscode existiert."""
    hr, requests_mod = _import_http_retry_with_fake_requests(monkeypatch)

    captured = {}

    def _fake_log_api_failure(service, url, reason, fallback_used=False, http_status=None):
        captured["http_status"] = http_status

    monkeypatch.setattr(hr, "log_api_failure", _fake_log_api_failure)
    monkeypatch.setattr(hr, "log_api_call", lambda *a, **k: None)
    monkeypatch.setattr(hr.time, "sleep", lambda *_: None)

    def _fake_get(url, timeout, **kwargs):
        raise requests_mod.exceptions.Timeout("simulierter Timeout")

    monkeypatch.setattr(hr._SESSION, "get", _fake_get)

    with pytest.raises(requests_mod.exceptions.Timeout):
        hr.retry_get(
            "https://api.open-meteo.com/v1/forecast",
            service="Open-Meteo-Outlook",
            max_retries=2,
            backoff=[0, 0],
        )

    assert captured["http_status"] is None


def test_4xx_sonderpfad_bleibt_unveraendert(monkeypatch):
    """Regression: der bestehende 4xx-Sonderpfad (abort_on_4xx) uebergab
    http_status bereits vorher korrekt — B330 darf ihn nicht veraendern."""
    hr, requests_mod = _import_http_retry_with_fake_requests(monkeypatch)

    captured = {}

    def _fake_log_api_failure(service, url, reason, fallback_used=False, http_status=None):
        captured["http_status"] = http_status
        captured["reason"] = reason

    monkeypatch.setattr(hr, "log_api_failure", _fake_log_api_failure)
    monkeypatch.setattr(hr, "log_api_call", lambda *a, **k: None)
    monkeypatch.setattr(hr.time, "sleep", lambda *_: None)

    def _fake_get(url, timeout, **kwargs):
        return _FakeResponse(404)

    monkeypatch.setattr(hr._SESSION, "get", _fake_get)

    with pytest.raises(requests_mod.exceptions.HTTPError):
        hr.retry_get(
            "https://api.open-meteo.com/v1/forecast",
            service="Open-Meteo-Outlook",
            max_retries=3,
            backoff=[0, 0],
            abort_on_4xx=True,
        )

    assert captured["http_status"] == 404
    assert captured["reason"] == "http-404"
