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
from debug_utils import debug_log, log_api_failure, log_api_call, log_http_response

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


# Maximale erlaubte Einzeldatei-Größe nach Extract (50 MB).
# ARSO KMZ enthält 1 KML (<10 KB) und 1 PNG (typisch 100–500 KB).
_MAX_EXTRACT_FILE_SIZE = 50 * 1024 * 1024


def _safe_extract_kmz(zf: zipfile.ZipFile, dest_dir: str) -> list:
    """
    Sichere Extraktion eines ZIP/KMZ-Archivs (Fix P05, Zip-Slip-Schutz).

    Lehnt ab:
      - Einträge mit absoluten Pfaden
      - Einträge die durch Normalisierung das Zielverzeichnis verlassen
      - Symlinks und Sondertypen
      - Einzeldateien > _MAX_EXTRACT_FILE_SIZE

    Gibt die Liste der erfolgreich extrahierten Dateinamen zurück.
    """
    extracted = []
    dest_abs = os.path.realpath(os.path.abspath(dest_dir))
    os.makedirs(dest_abs, exist_ok=True)

    for info in zf.infolist():
        name = info.filename
        # 1) Sondertypen ausschließen (Symlinks: external_attr top-byte = 0xA1)
        is_symlink = (info.external_attr >> 28) == 0xA
        if is_symlink:
            debug_log(f"[RADAR] Lehne Symlink ab: {name}")
            continue
        # 2) Absoluter Pfad?
        if name.startswith("/") or name.startswith("\\"):
            debug_log(f"[RADAR] Lehne absoluten Pfad ab: {name}")
            continue
        # 3) Windows-Drive-Letter?
        if len(name) >= 2 and name[1] == ":":
            debug_log(f"[RADAR] Lehne Drive-Letter-Pfad ab: {name}")
            continue
        # 4) Pfad normalisieren und prüfen, ob er dest_abs verlässt
        target = os.path.realpath(os.path.abspath(os.path.join(dest_abs, name)))
        if not (target == dest_abs or target.startswith(dest_abs + os.sep)):
            debug_log(f"[RADAR] Lehne Path-Traversal ab: {name} → {target}")
            continue
        # 5) Verzeichniseinträge anlegen
        if name.endswith("/") or name.endswith("\\"):
            os.makedirs(target, exist_ok=True)
            continue
        # 6) Größenlimit
        if info.file_size > _MAX_EXTRACT_FILE_SIZE:
            debug_log(
                f"[RADAR] Lehne übergroßen Eintrag ab: {name} "
                f"({info.file_size} > {_MAX_EXTRACT_FILE_SIZE} Bytes)"
            )
            continue
        # 7) Tatsächlich extrahieren
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with zf.open(info, "r") as src, open(target, "wb") as dst:
            dst.write(src.read())
        extracted.append(name)

    return extracted


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
            import time as _t_radar
            _t0_radar = _t_radar.monotonic()
            response = requests.get(
                KMZ_URL, headers=req_headers, timeout=_TIMEOUT
            )
            _kmz_save_path = KMZ_PATH if response.status_code == 200 else None
            log_http_response(
                service="arso_radar",
                method="GET",
                response=response,
                duration_ms=(_t_radar.monotonic() - _t0_radar) * 1000,
                saved_to=_kmz_save_path,
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

    # Entpacken (Fix P05: Zip-Slip-Schutz via _safe_extract_kmz)
    try:
        with zipfile.ZipFile(KMZ_PATH, "r") as zf:
            extracted = _safe_extract_kmz(zf, "data")
            if not extracted:
                debug_log("[RADAR] Sicheres Entpacken hat keine Dateien geliefert.")
                log_api_failure(
                    "ARSO-Radar", KMZ_URL,
                    "unzip-error: keine sicheren Einträge im Archiv",
                    fallback_used=False,
                )
                return False
            for name in extracted:
                if name.endswith(".kml"):
                    src_path = os.path.join("data", name)
                    if os.path.exists("data/latest.kml"):
                        os.remove("data/latest.kml")
                    os.rename(src_path, "data/latest.kml")
                if name.endswith(".png"):
                    src_path = os.path.join("data", name)
                    if os.path.exists("data/latest.png"):
                        os.remove("data/latest.png")
                    os.rename(src_path, "data/latest.png")
    except Exception as e:
        debug_log(f"[RADAR] Entpacken fehlgeschlagen: {e}")
        log_api_failure("ARSO-Radar", KMZ_URL,
                        f"unzip-error: {e}", fallback_used=False)
        return False

    debug_log("Radarbild und KML erfolgreich heruntergeladen und entpackt.")
    return True
