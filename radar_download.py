# radar_download.py
"""
Lädt das aktuelle ARSO INCA si0zm Radar-KMZ herunter.
Hardening: If-Modified-Since (1 Request statt 2), Timeout 30s,
User-Agent, 3 Retries mit exponentiellem Backoff, log_api_failure.
"""
import os
import time
import requests
import zipfile
from email.utils import formatdate, parsedate_to_datetime
from debug_utils import debug_log, log_api_failure

KMZ_URL  = "https://meteo.arso.gov.si/uploads/probase/www/nowcast/inca/inca_si0zm_latest.kmz"
KMZ_PATH = "weather_data.kmz"
_LAST_MODIFIED_FILE = "data/.kmz_last_modified"

_HEADERS = {
    "User-Agent": "WetterExtended/1.0 (Raspberry Pi 5; Kaernten weather tracking)"
}
_TIMEOUT      = 30
_MAX_RETRIES  = 3
_RETRY_BACKOFF = [2, 5, 10]


def _read_last_modified() -> str | None:
    """Liest den zuletzt bekannten Last-Modified-Wert aus der Cache-Datei."""
    try:
        if os.path.exists(_LAST_MODIFIED_FILE):
            with open(_LAST_MODIFIED_FILE, "r") as f:
                return f.read().strip() or None
    except Exception:
        pass
    return None


def _write_last_modified(value: str) -> None:
    """Speichert den Last-Modified-Wert für den nächsten Zyklus."""
    try:
        os.makedirs(os.path.dirname(_LAST_MODIFIED_FILE), exist_ok=True)
        with open(_LAST_MODIFIED_FILE, "w") as f:
            f.write(value)
    except Exception:
        pass


def download_kmz() -> bool:
    """
    Lädt ARSO INCA KMZ herunter, entpackt und legt kml/png als data/latest.* ab.
    Nutzt If-Modified-Since → 304 wenn kein neues Bild (kein Download).
    Gibt True zurück wenn neues Bild verarbeitet wurde, False sonst.
    """
    os.makedirs("data", exist_ok=True)

    # If-Modified-Since Header aufbauen
    last_modified = _read_last_modified()
    req_headers   = dict(_HEADERS)
    if last_modified:
        req_headers["If-Modified-Since"] = last_modified

    # GET mit Retries (If-Modified-Since → 304 oder 200)
    last_exc: Exception = Exception("Unbekannter Fehler")
    response = None

    for attempt in range(_MAX_RETRIES):
        try:
            response = requests.get(
                KMZ_URL, headers=req_headers, timeout=_TIMEOUT
            )

            if response.status_code == 304:
                debug_log("Kein neues Radarbild verfügbar (304 Not Modified).")
                return False

            response.raise_for_status()

            with open(KMZ_PATH, "wb") as f:
                f.write(response.content)

            # Last-Modified für nächsten Zyklus speichern
            new_lm = response.headers.get("Last-Modified")
            if new_lm:
                _write_last_modified(new_lm)

            break  # Erfolg

        except requests.exceptions.Timeout as exc:
            last_exc = exc
            debug_log(f"[RADAR] Timeout (Versuch {attempt + 1}/{_MAX_RETRIES})")
        except requests.exceptions.HTTPError as exc:
            last_exc = exc
            status = getattr(exc.response, "status_code", None)
            debug_log(f"[RADAR] HTTP-Fehler {status} (Versuch {attempt + 1}/{_MAX_RETRIES})")
            if status and 400 <= status < 500:
                log_api_failure("ARSO-Radar", KMZ_URL,
                                f"http-{status}", fallback_used=False,
                                http_status=status)
                return False
        except Exception as exc:
            last_exc = exc
            debug_log(f"[RADAR] Fehler (Versuch {attempt + 1}/{_MAX_RETRIES}): {exc}")

        if attempt < _MAX_RETRIES - 1:
            wait = _RETRY_BACKOFF[attempt]
            debug_log(f"[RADAR] Warte {wait}s vor erneutem Versuch...")
            time.sleep(wait)
    else:
        log_api_failure("ARSO-Radar", KMZ_URL,
                        f"{type(last_exc).__name__}: {last_exc}", fallback_used=False)
        debug_log(f"[RADAR] Alle {_MAX_RETRIES} Versuche fehlgeschlagen.")
        return False

    # Validierung
    if not zipfile.is_zipfile(KMZ_PATH):
        debug_log("[RADAR] Heruntergeladene Datei ist keine gültige KMZ/ZIP-Datei.")
        log_api_failure("ARSO-Radar", KMZ_URL, "invalid-zip", fallback_used=False)
        return False

    # Entpacken
    try:
        with zipfile.ZipFile(KMZ_PATH, "r") as zf:
            zf.extractall("data")
            for name in zf.namelist():
                if name.endswith(".kml"):
                    if os.path.exists("data/latest.kml"):
                        os.remove("data/latest.kml")
                    os.rename(f"data/{name}", "data/latest.kml")
                if name.endswith(".png"):
                    if os.path.exists("data/latest.png"):
                        os.remove("data/latest.png")
                    os.rename(f"data/{name}", "data/latest.png")
    except Exception as e:
        debug_log(f"[RADAR] Entpacken fehlgeschlagen: {e}")
        log_api_failure("ARSO-Radar", KMZ_URL,
                        f"unzip-error: {e}", fallback_used=False)
        return False

    debug_log("Radarbild und KML erfolgreich heruntergeladen und entpackt.")
    return True
