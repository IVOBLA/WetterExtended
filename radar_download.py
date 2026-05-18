# radar_download.py
"""
Lädt das aktuelle ARSO INCA si0zm Radar-KMZ herunter.
Hardening: Timeout 30 s, User-Agent, 3 Retries mit exponentiellem Backoff,
log_api_failure bei dauerhaftem Fehler.
"""
import os
import time
import requests
import zipfile
from email.utils import parsedate_to_datetime
from debug_utils import debug_log, log_api_failure

KMZ_URL = "https://meteo.arso.gov.si/uploads/probase/www/nowcast/inca/inca_si0zm_latest.kmz"
KMZ_PATH = "weather_data.kmz"

_HEADERS = {
    "User-Agent": "WetterExtended/1.0 (Raspberry Pi 5; Kaernten weather tracking)"
}
_TIMEOUT = 30
_MAX_RETRIES = 3
_RETRY_BACKOFF = [2, 5, 10]   # Wartezeit in Sekunden zwischen den Versuchen


def download_kmz() -> bool:
    """
    Lädt ARSO INCA KMZ herunter, entpackt und legt kml/png als data/latest.* ab.
    Gibt True zurück wenn neues Bild vorliegt, False wenn kein Update oder Fehler.
    """
    os.makedirs("data", exist_ok=True)

    # HEAD-Check: ist das Bild neuer als der letzte Download?
    try:
        last_download = os.path.getmtime(KMZ_PATH) if os.path.exists(KMZ_PATH) else 0
        head_resp = requests.head(
            KMZ_URL, headers=_HEADERS, allow_redirects=True, timeout=10
        )
        remote_time = head_resp.headers.get("Last-Modified")
        if remote_time:
            remote_ts = parsedate_to_datetime(remote_time).timestamp()
            if remote_ts <= last_download:
                debug_log("Kein neues Radarbild verfügbar.")
                return False
    except Exception as e:
        debug_log(f"[RADAR] Zeitprüfung fehlgeschlagen: {e} — lade trotzdem.")

    # GET mit Retries und exponentiellem Backoff
    last_exc: Exception = Exception("Unbekannter Fehler")
    for attempt in range(_MAX_RETRIES):
        try:
            response = requests.get(KMZ_URL, headers=_HEADERS, timeout=_TIMEOUT)
            response.raise_for_status()
            with open(KMZ_PATH, "wb") as f:
                f.write(response.content)
            break  # Erfolg — Schleife verlassen
        except requests.exceptions.Timeout as exc:
            last_exc = exc
            debug_log(f"[RADAR] Timeout (Versuch {attempt + 1}/{_MAX_RETRIES})")
        except requests.exceptions.HTTPError as exc:
            last_exc = exc
            status = getattr(exc.response, "status_code", None)
            debug_log(f"[RADAR] HTTP-Fehler {status} (Versuch {attempt + 1}/{_MAX_RETRIES})")
            # 4xx: kein Retry sinnvoll
            if status and 400 <= status < 500:
                log_api_failure("ARSO-Radar", KMZ_URL,
                                f"http-{status}", fallback_used=False,
                                http_status=status)
                return False
        except Exception as exc:
            last_exc = exc
            debug_log(f"[RADAR] Download-Fehler (Versuch {attempt + 1}/{_MAX_RETRIES}): {exc}")

        if attempt < _MAX_RETRIES - 1:
            wait = _RETRY_BACKOFF[attempt]
            debug_log(f"[RADAR] Warte {wait} s vor erneutem Versuch...")
            time.sleep(wait)
    else:
        # Alle Retries ausgeschöpft
        log_api_failure(
            "ARSO-Radar", KMZ_URL,
            f"{type(last_exc).__name__}: {last_exc}", fallback_used=False,
        )
        debug_log(f"[RADAR] Alle {_MAX_RETRIES} Versuche fehlgeschlagen.")
        return False

    # Validierung und Entpacken
    if not zipfile.is_zipfile(KMZ_PATH):
        debug_log("[RADAR] Heruntergeladene Datei ist keine gültige KMZ/ZIP-Datei.")
        log_api_failure("ARSO-Radar", KMZ_URL, "invalid-zip", fallback_used=False)
        return False

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
