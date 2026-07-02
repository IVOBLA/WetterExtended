"""
Einheitlicher Retry-Wrapper für externe HTTP-GET-Requests.

Resilienz-Schichten:
  1. urllib3-Retry im HTTPAdapter (status_forcelist=[429,500,502,503,504],
     respect Retry-After, backoff_factor=1.0, abdeckt Connection-Level-Fehler
     inkl. SSLEOFError, ProtocolError, IncompleteRead)
  2. Äußerer Python-Loop (max_retries=3) mit exponentiellem Backoff
     für Timeouts und sonstige Exceptions
  3. Globale requests.Session: HTTP-Connection-Pool wird zwischen Aufrufen
     wiederverwendet (Keepalive); bei TLS-EOF wird die kaputte Verbindung
     aus dem Pool entfernt und beim nächsten Versuch neu aufgebaut.

API-Vertrag bleibt rückwärtskompatibel:
    from http_retry import retry_get
    r = retry_get(url, service="MyAPI", timeout=15, auth=(...), params=[...])
"""

import time

import requests
from requests.adapters import HTTPAdapter

try:
    # urllib3 v2.x: 'allowed_methods', v1.x: 'method_whitelist'
    from urllib3.util.retry import Retry
except ImportError:
    from urllib3.util import Retry  # ältere urllib3

from debug_utils import debug_log, log_api_failure, log_api_call

try:
    import api_circuit_breaker
except Exception:  # Breaker optional — retry_get bleibt ohne ihn nutzbar
    api_circuit_breaker = None

try:
    import api_budget_guard
except Exception:  # Budget-Guard optional — retry_get bleibt ohne ihn nutzbar
    api_budget_guard = None


class CircuitOpenError(requests.exceptions.RequestException):
    """B149: Circuit-Breaker für diesen Service ist offen — Request übersprungen.
    Subklasse von RequestException, damit bestehende except-Blöcke der Fetcher
    (RequestException/Exception) den Fallback wie bei jedem anderen Fehler greifen."""


class BudgetExceededError(requests.exceptions.RequestException):
    """1E: Tagesbudget der Service-Gruppe erschöpft — Request übersprungen.
    Subklasse von RequestException, damit bestehende except-Blöcke der Fetcher
    den Fallback (Stale-Cache) wie bei jedem anderen Fehler greifen."""


_DEFAULT_BACKOFF = [2]
_DEFAULT_CONNECT_TIMEOUT = 5
_DEFAULT_READ_TIMEOUT = 15


def _build_session() -> requests.Session:
    """
    Baut die globale Session genau einmal beim Modul-Import.
    HTTPAdapter mit Retry verteilt automatisch auf 502/503/504/429
    UND auf Connection-Errors (inkl. SSL EOF).
    """
    s = requests.Session()
    try:
        # urllib3 v2.x: 'allowed_methods'
        retry = Retry(
            total=1,
            connect=1,
            read=0,
            status=1,
            backoff_factor=1.0,  # 1 s, 2 s, 4 s (urllib3-intern)
            status_forcelist=(500, 502, 503, 504),
            allowed_methods=frozenset(["GET", "HEAD"]),
            respect_retry_after_header=True,
            raise_on_status=False,  # 5xx wird dem Caller als raise_for_status() überlassen
        )
    except TypeError:
        # urllib3 v1.x Fallback
        retry = Retry(
            total=1,
            connect=1,
            read=0,
            status=1,
            backoff_factor=1.0,
            status_forcelist=(500, 502, 503, 504),
            method_whitelist=frozenset(["GET", "HEAD"]),
        )
    adapter = HTTPAdapter(
        pool_connections=10,
        pool_maxsize=20,
        max_retries=retry,
        pool_block=False,
    )
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    # User-Agent macht Logs auf Anbieter-Seite identifizierbar (Goodwill-Faktor)
    s.headers.update({"User-Agent": "WetterExtended/1.x (+https://github.com/IVOBLA/WetterExtended)"})
    return s


_SESSION = _build_session()


def _normalize_timeout(timeout):
    """
    Akzeptiert int, float oder Tuple. Int → (connect, max(int, read_default)).
    """
    if isinstance(timeout, tuple) and len(timeout) == 2:
        return timeout
    if timeout is None:
        return (_DEFAULT_CONNECT_TIMEOUT, _DEFAULT_READ_TIMEOUT)
    try:
        t = float(timeout)
        return (_DEFAULT_CONNECT_TIMEOUT, max(t, _DEFAULT_READ_TIMEOUT))
    except (TypeError, ValueError):
        return (_DEFAULT_CONNECT_TIMEOUT, _DEFAULT_READ_TIMEOUT)


def retry_get(
    url: str,
    *,
    service: str = "HTTP",
    max_retries: int = 2,
    backoff: list | None = None,
    timeout=15,
    abort_on_4xx: bool = True,
    breaker_service: str | None = None,
    **kwargs,
) -> requests.Response:
    """
    GET-Request mit zwei Retry-Schichten (Session-Adapter + Python-Loop).
    Wirft beim endgültigen Scheitern die letzte Exception (analog Vorgänger).

    B149: Ist `breaker_service` (kanonischer Service-Name, z. B. "geosphere_nowcast")
    gesetzt, führt retry_get den Circuit-Breaker zentral:
      - is_open(breaker_service) vor dem Senden → CircuitOpenError (Caller fällt zurück),
      - record_success() bei Erfolg,
      - record_failure() bei 429/5xx/Timeout/Connection/SSL (max. 1× pro Aufruf).
    Ohne `breaker_service` bleibt das Verhalten unverändert (rückwärtskompatibel).
    """
    if backoff is None:
        backoff = _DEFAULT_BACKOFF

    # B149: Circuit-Breaker zentral. Ist der Service offen, gar nicht erst senden.
    if breaker_service and api_circuit_breaker and api_circuit_breaker.is_open(breaker_service):
        debug_log(f"[{service}] Circuit offen ({breaker_service}) — Request übersprungen")
        if api_budget_guard is not None:
            api_budget_guard.record_blocked_by_circuit(service)
        raise CircuitOpenError(f"circuit open: {breaker_service}")

    # 1E: Budget-Guard zentral. Ist das Tagesbudget der Gruppe erschöpft, gar nicht senden.
    if api_budget_guard is not None and api_budget_guard.over_budget(service):
        debug_log(f"[{service}] Tagesbudget erschöpft — Request übersprungen")
        raise BudgetExceededError(f"budget exceeded: {service}")

    tmo = _normalize_timeout(timeout)
    last_exc: Exception = RuntimeError("Unbekannter Fehler")

    for attempt in range(max_retries):
        try:
            if api_budget_guard is not None:
                api_budget_guard.record_request(service)
            r = _SESSION.get(url, timeout=tmo, **kwargs)
            r.raise_for_status()
            if breaker_service and api_circuit_breaker:
                api_circuit_breaker.record_success(breaker_service)
            return r
        except requests.exceptions.Timeout as exc:
            last_exc = exc
            debug_log(f"[{service}] Timeout (Versuch {attempt + 1}/{max_retries}, timeout={tmo})")
        except requests.exceptions.HTTPError as exc:
            last_exc = exc
            status = getattr(exc.response, "status_code", None)
            debug_log(f"[{service}] HTTP {status} (Versuch {attempt + 1}/{max_retries})")
            if abort_on_4xx and status and 400 <= status < 500:
                try:
                    exc.retry_after = int(exc.response.headers.get("Retry-After")) if exc.response and exc.response.headers.get("Retry-After") else None
                except Exception:
                    exc.retry_after = None
                if breaker_service and api_circuit_breaker:
                    # 429 öffnet sofort (mit Retry-After); andere 4xx zählen nicht zum Öffnen.
                    api_circuit_breaker.record_failure(
                        breaker_service, f"http-{status}",
                        http_status=status, retry_after=getattr(exc, "retry_after", None),
                    )
                log_api_failure(
                    service,
                    url,
                    f"http-{status}",
                    fallback_used=True,
                    http_status=status,
                )
                # In api_call_counts loggen → Dashboard zeigt Fehler-Request + Response
                _err_body = None
                try:
                    _err_body = (exc.response.text or "")[:500] if exc.response else None
                except Exception:
                    pass
                log_api_call(service, url=url, status_code=status, method="GET",
                             response_text=_err_body, error=f"http-{status}")
                raise
        except requests.exceptions.SSLError as exc:
            # Spezialfall: TLS-EOF / SSLZeroReturnError.
            # Session-Adapter hat bereits intern wiederholt — wenn wir hier landen,
            # ist die Verbindung dauerhaft gestört. Trotzdem nochmal mit Wait.
            last_exc = exc
            debug_log(
                f"[{service}] SSL-Fehler (Versuch {attempt + 1}/{max_retries}): "
                f"{type(exc).__name__}: {str(exc)}"
            )
            if breaker_service and api_circuit_breaker:
                api_circuit_breaker.record_failure(breaker_service, "SSLError")
            raise
        except requests.exceptions.ConnectionError as exc:
            last_exc = exc
            debug_log(
                f"[{service}] Connection-Fehler (Versuch {attempt + 1}/{max_retries}): "
                f"{type(exc).__name__}: {str(exc)}"
            )
        except Exception as exc:
            last_exc = exc
            debug_log(
                f"[{service}] Fehler (Versuch {attempt + 1}/{max_retries}): "
                f"{type(exc).__name__}: {str(exc)}"
            )

        if attempt < max_retries - 1:
            wait = backoff[attempt] if attempt < len(backoff) else backoff[-1]
            debug_log(f"[{service}] Warte {wait}s vor erneutem Versuch...")
            time.sleep(wait)

    _last_err_str = f"{type(last_exc).__name__}: {str(last_exc)}"
    if breaker_service and api_circuit_breaker:
        _b_status = None
        if isinstance(last_exc, requests.exceptions.HTTPError):
            _b_status = getattr(getattr(last_exc, "response", None), "status_code", None)
            _b_reason = f"http-{_b_status}" if _b_status else "HTTPError"
        elif isinstance(last_exc, requests.exceptions.Timeout):
            _b_reason = "Timeout"
        elif isinstance(last_exc, requests.exceptions.SSLError):
            _b_reason = "SSLError"
        elif isinstance(last_exc, requests.exceptions.ConnectionError):
            _b_reason = "ConnectionError"
        else:
            _b_reason = type(last_exc).__name__
        api_circuit_breaker.record_failure(breaker_service, _b_reason, http_status=_b_status)
    log_api_failure(service, url, _last_err_str, fallback_used=True)
    # In api_call_counts loggen → Dashboard zeigt fehlgeschlagene Requests
    _last_resp_text = None
    try:
        if hasattr(last_exc, "response") and last_exc.response is not None:
            _last_resp_text = (last_exc.response.text or "")[:500]
    except Exception:
        pass
    log_api_call(service, url=url, status_code=0, method="GET",
                 response_text=_last_resp_text, error=_last_err_str)
    raise last_exc
