"""
Einheitlicher Retry-Wrapper für externe HTTP-GET-Requests.

Alle WetterExtended-APIs (außer radar_download, der einen eigenen Loop hat)
nutzen retry_get() statt direkter requests.get()-Aufrufe. Dadurch:
  - Konsistente Retry-Logik mit exponentiellem Backoff
  - Einheitliches Fehler-Logging via log_api_failure
  - Kein Code-Duplikat in jedem API-Modul

Verwendung:
    from http_retry import retry_get
    r = retry_get(url, service="MyAPI", timeout=15, auth=(...))
"""

import time
import requests

from debug_utils import debug_log, log_api_failure

_DEFAULT_BACKOFF = [2, 5, 10]


def retry_get(
    url: str,
    *,
    service: str = "HTTP",
    max_retries: int = 3,
    backoff: list | None = None,
    timeout: int = 15,
    abort_on_4xx: bool = True,
    **kwargs,
) -> requests.Response:
    """
    GET-Request mit Retry und exponentiellem Backoff.
    """
    if backoff is None:
        backoff = _DEFAULT_BACKOFF

    last_exc: Exception = RuntimeError("Unbekannter Fehler")

    for attempt in range(max_retries):
        try:
            r = requests.get(url, timeout=timeout, **kwargs)
            r.raise_for_status()
            return r
        except requests.exceptions.Timeout as exc:
            last_exc = exc
            debug_log(f"[{service}] Timeout (Versuch {attempt + 1}/{max_retries})")
        except requests.exceptions.HTTPError as exc:
            last_exc = exc
            status = getattr(exc.response, "status_code", None)
            debug_log(f"[{service}] HTTP {status} (Versuch {attempt + 1}/{max_retries})")
            if abort_on_4xx and status and 400 <= status < 500:
                log_api_failure(
                    service, url, f"http-{status}",
                    fallback_used=True, http_status=status,
                )
                raise
        except Exception as exc:
            last_exc = exc
            debug_log(
                f"[{service}] Fehler (Versuch {attempt + 1}/{max_retries}): "
                f"{type(exc).__name__}: {exc}"
            )

        if attempt < max_retries - 1:
            wait = backoff[attempt] if attempt < len(backoff) else backoff[-1]
            debug_log(f"[{service}] Warte {wait}s vor erneutem Versuch...")
            time.sleep(wait)

    log_api_failure(
        service, url,
        f"{type(last_exc).__name__}: {last_exc}",
        fallback_used=True,
    )
    raise last_exc
