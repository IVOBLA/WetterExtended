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
from datetime import datetime
from email.utils import formatdate, parsedate_to_datetime
from debug_utils import debug_log, log_api_failure, log_api_call, log_http_response

KMZ_URL  = "https://meteo.arso.gov.si/uploads/probase/www/nowcast/inca/inca_si0zm_latest.kmz"
KMZ_PATH = "weather_data.kmz"
_LAST_MODIFIED_FILE  = "data/.kmz_last_modified"
_CONTENT_HASH_FILE   = "data/.kmz_content_sha256"
_LATEST_KML_FILE     = "data/latest.kml"   # B122: Quelle für echte Valid-Time


def _read_content_hash() -> str | None:
    """P2-1: Liest den SHA256-Hash des letzten KMZ-Inhalts."""
    try:
        if os.path.exists(_CONTENT_HASH_FILE):
            with open(_CONTENT_HASH_FILE, "r") as f:
                return f.read().strip() or None
    except Exception:
        pass
    return None


def _write_content_hash(content: bytes) -> None:
    """P2-1: Speichert den SHA256-Hash des heruntergeladenen Inhalts."""
    import hashlib
    try:
        digest = hashlib.sha256(content).hexdigest()
        os.makedirs(os.path.dirname(_CONTENT_HASH_FILE), exist_ok=True)
        with open(_CONTENT_HASH_FILE, "w") as f:
            f.write(digest)
    except Exception:
        pass

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


def _acq_from_kml_timestamp() -> str | None:
    """B122: Liest die echte Valid-Time aus dem KML <TimeStamp><when>-Element.

    ARSO INCA si0zm liefert die Aufnahmezeit als ISO-8601 UTC, z.B.
    <TimeStamp><when>2026-06-11T05:15:00Z</when></TimeStamp>.

    Rückgabe: 'YYYY-MM-DD_HH-MM-SS' in Europe/Vienna-Lokalzeit oder None.
    """
    try:
        if not os.path.exists(_LATEST_KML_FILE):
            return None
        import re
        from zoneinfo import ZoneInfo
        with open(_LATEST_KML_FILE, "r", encoding="utf-8") as _f:
            kml = _f.read()
        m = re.search(r"<when>\s*([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})Z\s*</when>", kml)
        if not m:
            return None
        dt_utc = datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=ZoneInfo("UTC"))
        return dt_utc.astimezone(ZoneInfo("Europe/Vienna")).strftime("%Y-%m-%d_%H-%M-%S")
    except Exception:
        return None


def _acq_from_kml_pngname() -> str | None:
    """B122: Fallback — liest die Valid-Time aus dem PNG-Dateinamen in der KML.

    Pattern: inca_si0zm_YYYYMMDD-HHMM+0000.png (UTC).
    Rückgabe: 'YYYY-MM-DD_HH-MM-SS' in Europe/Vienna-Lokalzeit oder None.
    """
    try:
        if not os.path.exists(_LATEST_KML_FILE):
            return None
        import re
        from zoneinfo import ZoneInfo
        with open(_LATEST_KML_FILE, "r", encoding="utf-8") as _f:
            kml = _f.read()
        m = re.search(r"inca_si0zm_(\d{8})-(\d{4})\+0000", kml)
        if not m:
            return None
        dt_utc = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M").replace(tzinfo=ZoneInfo("UTC"))
        return dt_utc.astimezone(ZoneInfo("Europe/Vienna")).strftime("%Y-%m-%d_%H-%M-%S")
    except Exception:
        return None


def _acq_from_last_modified() -> str | None:
    """Aufnahmezeit aus dem HTTP Last-Modified-Header (B40, jetzt Fallback)."""
    raw = _read_last_modified()
    if not raw:
        return None
    try:
        from zoneinfo import ZoneInfo
        dt_utc = parsedate_to_datetime(raw)
        dt_vienna = dt_utc.astimezone(ZoneInfo("Europe/Vienna"))
        return dt_vienna.strftime("%Y-%m-%d_%H-%M-%S")
    except Exception:
        return None


def get_acquisition_timestamp() -> str | None:
    """
    Gibt den Aufnahme-Zeitstempel des zuletzt heruntergeladenen ARSO-KMZ zurück.

    B122: Quellen-Priorität (genaueste zuerst):
      1. KML <TimeStamp><when>  — echte Radar-Valid-Time (ISO-8601 UTC)
      2. PNG-Dateiname in der KML (inca_si0zm_YYYYMMDD-HHMM+0000)
      3. HTTP Last-Modified (data/.kmz_last_modified, RFC 2822) — Publikationszeit

    Rückgabe: 'YYYY-MM-DD_HH-MM-SS' in Europe/Vienna-Lokalzeit, oder None.
    """
    for _src in (_acq_from_kml_timestamp, _acq_from_kml_pngname, _acq_from_last_modified):
        _ts = _src()
        if _ts:
            return _ts
    return None


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

    # B156: Circuit-Breaker — bei offenem Service gar nicht erst anfragen.
    import api_circuit_breaker as _cb_radar
    if _cb_radar.is_open("arso_radar"):
        debug_log("[RADAR] Circuit offen (arso_radar) — Download übersprungen.")
        return False

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
                _cb_radar.record_success("arso_radar")
                return False

            response.raise_for_status()

            # P2-1: SHA256-Dedup — identischer Inhalt trotz neuem Last-Modified?
            import hashlib as _hl_radar
            _new_hash = _hl_radar.sha256(response.content).hexdigest()
            _prev_hash = _read_content_hash()
            if _prev_hash and _prev_hash == _new_hash:
                debug_log(
                    f"[RADAR] Inhalt unverändert (SHA256 identisch) — "
                    f"kein Tracking-Zyklus nötig."
                )
                _cb_radar.record_success("arso_radar")
                return False

            with open(KMZ_PATH, "wb") as f:
                f.write(response.content)

            # SHA256 + Last-Modified für nächsten Zyklus speichern
            _write_content_hash(response.content)
            new_lm = response.headers.get("Last-Modified")
            if new_lm:
                _write_last_modified(new_lm)

            _cb_radar.record_success("arso_radar")
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
                _cb_radar.record_failure("arso_radar", f"http-{status}", http_status=status)
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
        # B156: Reason/Status robust aus der letzten Exception ableiten und melden.
        import requests as _rq_radar
        if isinstance(last_exc, _rq_radar.exceptions.HTTPError):
            _st = getattr(getattr(last_exc, "response", None), "status_code", None)
            _rsn = f"http-{_st}" if _st else "HTTPError"
        elif isinstance(last_exc, _rq_radar.exceptions.Timeout):
            _st, _rsn = None, "Timeout"
        elif isinstance(last_exc, _rq_radar.exceptions.ConnectionError):
            _st, _rsn = None, "ConnectionError"
        else:
            _st, _rsn = None, type(last_exc).__name__
        _cb_radar.record_failure("arso_radar", _rsn, http_status=_st)
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
