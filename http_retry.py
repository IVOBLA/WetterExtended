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

from debug_utils import debug_log, log_api_failure

_DEFAULT_BACKOFF = [2, 5, 10]
_DEFAULT_CONNECT_TIMEOUT = 8  # TLS-Handshake darf bis 8 s dauern
_DEFAULT_READ_TIMEOUT = 30  # AROME-Bulk kann lang antworten


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
            total=3,
            connect=3,
            read=3,
            status=3,
            backoff_factor=1.0,  # 1 s, 2 s, 4 s (urllib3-intern)
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET", "HEAD"]),
            respect_retry_after_header=True,
            raise_on_status=False,  # 5xx wird dem Caller als raise_for_status() überlassen
        )
    except TypeError:
        # urllib3 v1.x Fallback
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            status=3,
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
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
    max_retries: int = 3,
    backoff: list | None = None,
    timeout=15,
    abort_on_4xx: bool = True,
    **kwargs,
) -> requests.Response:
    """
    GET-Request mit zwei Retry-Schichten (Session-Adapter + Python-Loop).
    Wirft beim endgültigen Scheitern die letzte Exception (analog Vorgänger).
    """
    if backoff is None:
        backoff = _DEFAULT_BACKOFF

    tmo = _normalize_timeout(timeout)
    last_exc: Exception = RuntimeError("Unbekannter Fehler")

    for attempt in range(max_retries):
        try:
            r = _SESSION.get(url, timeout=tmo, **kwargs)
            r.raise_for_status()
            return r
        except requests.exceptions.Timeout as exc:
            last_exc = exc
            debug_log(f"[{service}] Timeout (Versuch {attempt + 1}/{max_retries}, timeout={tmo})")
        except requests.exceptions.HTTPError as exc:
            last_exc = exc
            status = getattr(exc.response, "status_code", None)
            debug_log(f"[{service}] HTTP {status} (Versuch {attempt + 1}/{max_retries})")
            if abort_on_4xx and status and 400 <= status < 500:
                log_api_failure(
                    service,
                    url,
                    f"http-{status}",
                    fallback_used=True,
                    http_status=status,
                )
                raise
        except requests.exceptions.SSLError as exc:
            # Spezialfall: TLS-EOF / SSLZeroReturnError.
            # Session-Adapter hat bereits intern wiederholt — wenn wir hier landen,
            # ist die Verbindung dauerhaft gestört. Trotzdem nochmal mit Wait.
            last_exc = exc
            debug_log(
                f"[{service}] SSL-Fehler (Versuch {attempt + 1}/{max_retries}): "
                f"{type(exc).__name__}: {str(exc)[:120]}"
            )
        except requests.exceptions.ConnectionError as exc:
            last_exc = exc
            debug_log(
                f"[{service}] Connection-Fehler (Versuch {attempt + 1}/{max_retries}): "
                f"{type(exc).__name__}: {str(exc)[:120]}"
            )
        except Exception as exc:
            last_exc = exc
            debug_log(
                f"[{service}] Fehler (Versuch {attempt + 1}/{max_retries}): "
                f"{type(exc).__name__}: {str(exc)[:120]}"
            )

        if attempt < max_retries - 1:
            wait = backoff[attempt] if attempt < len(backoff) else backoff[-1]
            debug_log(f"[{service}] Warte {wait}s vor erneutem Versuch...")
            time.sleep(wait)

    log_api_failure(
        service,
        url,
        f"{type(last_exc).__name__}: {str(last_exc)[:120]}",
        fallback_used=True,
    )
    raise last_exc
