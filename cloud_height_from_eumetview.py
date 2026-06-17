# cloud_height_from_eumetview.py
"""
Lädt EUMETView IR108 GeoTIFF via WMS und berechnet Wolkenhöhe MSL je Zelle.

Hardening B11:
  - Alle Konsolen-Ausgaben durch debug_log() ersetzt
  - log_api_failure/log_api_call als Top-Level-Imports
  - EUMETView-Fehler erscheinen in /api/api_health
"""
import json
import os
import requests
import numpy as np
import xml.etree.ElementTree as ET
from datetime import datetime
from glob import glob
from typing import Any

from config import (
    BBOX_KAERNTEN_EXTENDED,
    SAVE_PATHS,
    EUMETVIEW_BT_MAX_K,
    EUMETVIEW_BT_MIN_K,
    EUMETVIEW_NODATA_PIXEL,
    EUMETVIEW_SCAN_MODE,
    EUMETVIEW_FES_LAYER_IR108,
    EUMETVIEW_RSS_LAYER_IR108,
    EUMETVIEW_LICENSE_STATUS,
    EUMETVIEW_PAID_ALLOWED,
)
from debug_utils import debug_log, log_api_failure, log_api_call, log_http_response
from api_cache import cache_key, cache_get, cache_set, get_ttl
import runtime_config

try:
    import rasterio
    from rasterio.transform import rowcol
    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False

try:
    import numpy as _np_check  # noqa: F401 — nur Import-Test
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

# ── Konstanten ───────────────────────────────────────────────────────────────
BBOX = [
    BBOX_KAERNTEN_EXTENDED["west"],
    BBOX_KAERNTEN_EXTENDED["south"],
    BBOX_KAERNTEN_EXTENDED["east"],
    BBOX_KAERNTEN_EXTENDED["north"],
]

WIDTH  = 1600
HEIGHT = 600
LAYER  = "msg_fes:ir108"
FORMAT = "image/geotiff"
# WMS 1.3.0 + EPSG:4326: Achsenreihenfolge Lat,Lon → BBOX-Interpretation falsch.
# Code sendet west,south,east,north (Lon,Lat) → Server interpretiert als Lat,Lon
# → völlig falsches Gebiet → TIFF: nur 0–3 statt 0–255 BT-Grauwerte.
# WMS 1.1.1: BBOX immer Lon,Lat,Lon,Lat unabhängig vom CRS → korrekt.
_WMS_VERSION = "1.1.1"    # 1.3.0 → 1.1.1
_WMS_SRS_KEY = "srs"      # WMS 1.3.0 nutzt "crs=", WMS 1.1.1 nutzt "srs="
CRS = "EPSG:4326"

SAVE_DIR            = SAVE_PATHS.get("cloud", "train_data/cloud/")
LAST_TIMESTAMP_FILE = os.path.join(SAVE_DIR, "last_wms_timestamp.txt")
_EVAL_DIR = SAVE_PATHS.get("evaluation", "train_data/evaluation").rstrip("/")
_EUMETVIEW_DEBUG_FILE = os.path.join(_EVAL_DIR, "eumetview_debug.jsonl")


# ── EUMETView Scan-Modus (FES/RSS) ─────────────────────────────────────────────
_GETCAPS_URL = (
    f"https://view.eumetsat.int/geoserver/wms"
    f"?service=WMS&request=GetCapabilities&version={_WMS_VERSION}"
)


def _norm_xml_tag(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _fetch_caps_root_for_resolve():
    """Holt GetCapabilities (über Circuit-Breaker) und liefert das geparste Root-
    Element oder None. Ausschließlich für die RSS-Layer-Validierung — die
    Timestamp-Auswertung bleibt in get_latest_wms_time."""
    try:
        from http_retry import retry_get
        r = retry_get(_GETCAPS_URL, service="EUMETView-WMS-Caps",
                      breaker_service="eumetview_capabilities", timeout=30)
        if not getattr(r, "ok", False):
            return None
        body = r.content or b""
        tail = body[-512:].lower()
        if (b"</wms_capabilities>" not in tail) and (b"</wmt_ms_capabilities>" not in tail):
            return None
        return ET.fromstring(body)
    except Exception as exc:
        debug_log(f"[CLOUD] RSS-Validierung: GetCapabilities-Fetch fehlgeschlagen: {exc}")
        return None


def _layer_in_capabilities(root, layer_name: str) -> bool:
    if root is None or not layer_name:
        return False
    for layer in root.iter():
        if _norm_xml_tag(layer.tag) != "Layer":
            continue
        for ch in list(layer):
            if _norm_xml_tag(ch.tag) == "Name" and (ch.text or "").strip() == layer_name:
                return True
    return False


def get_active_ir108_layer(caps_root_provider=None) -> str:
    """
    Liefert den zu verwendenden IR108-WMS-Layer abhängig vom Scan-Modus.

    FES (Default)  → EUMETVIEW_FES_LAYER_IR108 (~15 min), KEIN Caps-Fetch.
    RSS            → nur wenn Lizenz 'free_confirmed', PAID nicht erlaubt UND der
                     RSS-Layer in GetCapabilities existiert (validiert + gecacht).
                     Sonst Fallback auf FES.

    Es wird KEIN harter RSS-Layername angenommen. Im FES-Modus entsteht kein
    zusätzlicher Request (zieldefinition.txt: unnötige Fremdrequests vermeiden).
    """
    mode = str(runtime_config.get("EUMETVIEW_SCAN_MODE", EUMETVIEW_SCAN_MODE) or "FES").upper()
    fes = runtime_config.get("EUMETVIEW_FES_LAYER_IR108", EUMETVIEW_FES_LAYER_IR108)
    if mode != "RSS":
        return fes

    if str(runtime_config.get("EUMETVIEW_LICENSE_STATUS", EUMETVIEW_LICENSE_STATUS)) != "free_confirmed":
        debug_log("[CLOUD] RSS angefordert, aber Lizenz != free_confirmed → FES")
        return fes
    if bool(runtime_config.get("EUMETVIEW_PAID_ALLOWED", EUMETVIEW_PAID_ALLOWED)):
        debug_log("[CLOUD] Konfig-Konflikt: EUMETVIEW_PAID_ALLOWED=True bei Free-only → FES")
        return fes

    candidate = (
        runtime_config.get("EUMETVIEW_RSS_LAYER_IR108", EUMETVIEW_RSS_LAYER_IR108)
        or "msg_rss:ir108"
    )

    ck = cache_key("eumetview:active_layer", mode, candidate, _WMS_VERSION)
    cached = cache_get(ck, ttl_seconds=get_ttl("eumetview_capabilities", 600))
    if cached:
        return cached

    root = caps_root_provider() if caps_root_provider is not None else _fetch_caps_root_for_resolve()
    if _layer_in_capabilities(root, candidate):
        cache_set(ck, candidate)
        debug_log(f"[CLOUD] RSS-Layer '{candidate}' in GetCapabilities bestätigt → RSS aktiv")
        return candidate

    cache_set(ck, fes)   # negativen Befund cachen → kein wiederholter Caps-Fetch
    debug_log(f"[CLOUD] RSS-Layer '{candidate}' NICHT verfügbar → Fallback FES")
    return fes


# ── Hilfsfunktionen ──────────────────────────────────────────────────────────

def get_latest_wms_time() -> str | None:
    """
    Fragt EUMETView WMS GetCapabilities ab und gibt den aktuellen
    Zeitstempel des MSG IR108 Layers zurück.
    Cache 10 Min (MSG Full Earth Scan aktualisiert alle 15 Min).
    """
    # WMS-Version-Vereinheitlichung: GetMap nutzt _WMS_VERSION="1.1.1".
    # GetCapabilities muss dieselbe Version anfragen, sonst Inkonsistenz
    # bei Layer-Namen und Dimension-Format zwischen Versionen.
    url = (
        f"https://view.eumetsat.int/geoserver/wms"
        f"?service=WMS&request=GetCapabilities&version={_WMS_VERSION}"
    )
    _active_layer = get_active_ir108_layer()
    ck = cache_key("eumetview:capabilities", _active_layer, _WMS_VERSION)
    cached_ts = cache_get(ck, ttl_seconds=get_ttl("eumetview_capabilities", 600))
    if cached_ts is not None:
        debug_log(f"[CLOUD] WMS-Timestamp aus Cache: {cached_ts}")
        return cached_ts

    def _norm_tag(tag: str) -> str:
        return tag.split("}", 1)[-1] if "}" in tag else tag

    def _norm_time_iso(raw: str | None) -> str | None:
        if not raw or not isinstance(raw, str):
            return None
        v = raw.strip()
        if not v:
            return None
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(v)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            return None

    def _extract_last_iso_from_text(raw: str | None) -> str | None:
        if not raw:
            return None
        text = raw.strip()
        if not text:
            return None
        if "/" in text:
            parts = [p.strip() for p in text.split("/") if p.strip()]
            if len(parts) >= 2:
                return _norm_time_iso(parts[1])
        candidates = [c.strip() for c in text.replace(",", " ").split() if c.strip()]
        for cand in reversed(candidates):
            norm = _norm_time_iso(cand)
            if norm:
                return norm
        return None

    def _dbg(event: str, **kwargs: Any) -> None:
        rec = {
            "ts_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "event": event,
            "service": "EUMETView-WMS",
            "target_layer": _active_layer,
            "target_layer_found": False,
            "time_element_found": False,
            "raw_extent_default": None,
            "raw_extent_text_preview": None,
            "selected_timestamp": None,
            "timestamp_source": None,
            "reason": None,
        }
        rec.update(kwargs)
        try:
            os.makedirs(_EVAL_DIR, exist_ok=True)
            with open(_EUMETVIEW_DEBUG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass

    _dbg("capabilities_request", reason="start")
    try:
        import time as _t_wms_cap
        _t0_wms_cap = _t_wms_cap.monotonic()
        from http_retry import retry_get
        # B125: GetCapabilities ist ein großes Dokument — 10 s führten zu
        # abgeschnittenen Antworten (ParseError). Timeout erhöht.
        # B154: zentraler retry_get + Circuit-Breaker ("eumetview_capabilities").
        r = retry_get(url, service="EUMETView-WMS-Caps",
                      breaker_service="eumetview_capabilities", timeout=30)
        _dur_ms = (_t_wms_cap.monotonic() - _t0_wms_cap) * 1000
        log_http_response(
            service="eumetview_capabilities",
            method="GET",
            response=r,
            duration_ms=_dur_ms,
        )
        if r.ok:
            _dbg("capabilities_response", reason=f"http-{r.status_code}")
            # B125: Robustes Parsing — abgeschnittene Capabilities (ParseError /
            # fehlendes Schluss-Tag) bis zu 3x neu anfragen, bevor aufgegeben wird.
            root = None
            _caps_body = r.content
            for _b125_att in range(3):
                _tail = (_caps_body or b"")[-512:].lower()
                _complete = (b"</wms_capabilities>" in _tail) or (b"</wmt_ms_capabilities>" in _tail)
                if _complete:
                    try:
                        root = ET.fromstring(_caps_body)
                        break
                    except ET.ParseError:
                        _dbg("capabilities_response", reason=f"exception-ParseError-retry{_b125_att}")
                else:
                    _dbg("capabilities_response", reason=f"incomplete-capabilities-retry{_b125_att}")
                try:
                    # B160: Re-Fetch im Robustheits-Loop ebenfalls über den Breaker.
                    _rr = retry_get(url, service="EUMETView-WMS-Caps",
                                    breaker_service="eumetview_capabilities", timeout=30)
                    _caps_body = _rr.content if getattr(_rr, "ok", False) else b""
                except Exception:
                    _caps_body = b""
            if root is None:
                _dbg("timestamp_missing", reason="parse-failed-after-retries")
                return _caps_fallback("parse-failed-after-retries")
            target_layer = None
            for layer in root.iter():
                if _norm_tag(layer.tag) != "Layer":
                    continue
                for ch in list(layer):
                    if _norm_tag(ch.tag) == "Name" and (ch.text or "").strip() == _active_layer:
                        target_layer = layer
                        break
                if target_layer is not None:
                    break
            _dbg("target_layer_search", target_layer_found=bool(target_layer))
            if target_layer is None:
                _dbg("timestamp_missing", reason="target-layer-missing")
                return _caps_fallback("target-layer-missing")

            extent_default = None
            extent_text = None
            dim_default = None
            dim_text = None
            for elem in list(target_layer):
                tag = _norm_tag(elem.tag)
                n = (elem.attrib.get("name") or "").strip().lower()
                if n != "time":
                    continue
                txt = (elem.text or "").strip() or None
                if tag == "Extent":
                    extent_default = elem.attrib.get("default")
                    extent_text = txt
                elif tag == "Dimension":
                    dim_default = elem.attrib.get("default")
                    dim_text = txt

            _dbg(
                "time_dimension_search",
                target_layer_found=True,
                time_element_found=bool(extent_default or extent_text or dim_default or dim_text),
                raw_extent_default=extent_default,
                raw_extent_text_preview=(extent_text[:180] if extent_text else None),
            )

            selected = _norm_time_iso(extent_default)
            source = "extent-default"
            if not selected:
                selected = _norm_time_iso(dim_default)
                source = "dimension-default"
            if not selected:
                selected = _extract_last_iso_from_text(extent_text)
                source = "extent-text"
            if not selected:
                selected = _extract_last_iso_from_text(dim_text)
                source = "dimension-text"

            if selected:
                _dbg("timestamp_selected", target_layer_found=True, time_element_found=True, selected_timestamp=selected, timestamp_source=source)
                debug_log(f"[CLOUD] WMS-Timestamp gefunden: {selected}")
                cache_set(ck, selected)
                return selected
            _dbg("timestamp_missing", target_layer_found=True, time_element_found=False, reason="parser-no-timestamp")
    except Exception as e:
        debug_log(f"[CLOUD] GetCapabilities fehlgeschlagen: {e}")
        _dbg("capabilities_response", reason=f"exception-{type(e).__name__}")
        log_api_failure(
            "EUMETView-WMS", url, f"{type(e).__name__}: {e}", fallback_used=True
        )
    return _caps_fallback("capabilities-failed")


def wms_to_filename_timestamp(wms_time: str) -> str:
    dt = datetime.strptime(wms_time, "%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%d_%H-%M-%S")


def read_last_timestamp() -> str | None:
    if os.path.exists(LAST_TIMESTAMP_FILE):
        with open(LAST_TIMESTAMP_FILE, "r") as f:
            return f.read().strip()
    return None


# B174: Max. Alter (min) des wiederverwendeten letzten WMS-Timestamps, wenn
# GetCapabilities endgültig fehlschlägt (MSG-Full-Disk-Takt ~15 min).
# Optional via config.EUMETVIEW_FALLBACK_MAX_AGE_MIN überschreibbar.
EUMETVIEW_FALLBACK_MAX_AGE_MIN = 30.0


def _caps_fallback(reason: str):
    """B174: Bei endgültig fehlgeschlagener GetCapabilities-Auswertung den zuletzt
    erfolgreich verwendeten WMS-Timestamp wiederverwenden, sofern noch frisch genug.
    Verhindert, dass alle Objekte auf cloud_height_missing=1.0 degradieren, ohne
    veraltete IR-Daten einzuspeisen. Liefert None bei fehlendem/zu altem/unparsbarem
    Timestamp."""
    try:
        from config import EUMETVIEW_FALLBACK_MAX_AGE_MIN as _max_age
    except Exception:
        _max_age = EUMETVIEW_FALLBACK_MAX_AGE_MIN
    # RSS aktualisiert ~5 min → kürzeres Fallback-Fenster als FES (~15 min).
    try:
        if str(runtime_config.get("EUMETVIEW_SCAN_MODE", "FES")).upper() == "RSS":
            from config import EUMETVIEW_RSS_FALLBACK_MAX_AGE_MIN as _rss_age_def
            _max_age = float(
                runtime_config.get("EUMETVIEW_RSS_FALLBACK_MAX_AGE_MIN", _rss_age_def)
            )
    except Exception:
        pass
    last = read_last_timestamp()
    if not last:
        debug_log(f"[CLOUD] Fallback nicht möglich ({reason}): kein letzter Timestamp")
        return None
    try:
        _dt = datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ")
        _age_min = (datetime.utcnow() - _dt).total_seconds() / 60.0
    except Exception:
        debug_log(f"[CLOUD] Fallback nicht möglich ({reason}): letzter Timestamp unparsbar ({last})")
        return None
    if _age_min > float(_max_age):
        debug_log(
            f"[CLOUD] Fallback verworfen ({reason}): letzter Timestamp zu alt "
            f"({int(_age_min)} min > {int(float(_max_age))} min)"
        )
        return None
    debug_log(
        f"[CLOUD] Fallback auf letzten WMS-Timestamp ({reason}): {last} "
        f"({int(_age_min)} min alt)"
    )
    return last


def write_last_timestamp(ts: str) -> None:
    with open(LAST_TIMESTAMP_FILE, "w") as f:
        f.write(ts)
    debug_log(f"[CLOUD] Timestamp gespeichert: {ts}")


def build_tiff_url(timestamp: str) -> str:
    bbox_str = f"{BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]}"
    _layer = get_active_ir108_layer()
    return (
        f"https://view.eumetsat.int/geoserver/wms?"
        f"service=WMS&version={_WMS_VERSION}&request=GetMap"
        f"&layers={_layer}&styles=&format={FORMAT}&transparent=false"
        f"&{_WMS_SRS_KEY}={CRS}&bbox={bbox_str}&width={WIDTH}&height={HEIGHT}"
        f"&time={timestamp}"
    )


def get_adaptive_nan_threshold(utc_hour: int) -> float:
    """
    BT-Schwelle (Kelvin) ÜBER der kein Konvektionswolkentop angenommen wird.
    Nach _uint8_to_bt_kelvin liegt bt_k zwischen 180 K (Pixelwert 255, hohe
    Wolke) und 330 K (Pixelwert 0, warme Erdoberfläche).

    Physikalische Referenz MSG IR108:
      < 220 K  = sehr hohe Wolke (Cb-Amboss)
      220–250 K = hohe Wolke (Ci, hoher Cu)
      250–265 K = mittelhohe Konvektionswolke
      > 265 K  = warme Erdoberfläche oder tiefe Wolke → kein Wolkentop

    Tagsüber (6–18 UTC): 265 K
    Dämmerung (3–6 / 18–21 UTC): 260 K
    Nachts: 255 K (IR-Kontrast besser, strengerer Threshold sinnvoll)
    """
    if 6 <= utc_hour <= 18:
        return 265.0
    elif 3 <= utc_hour < 6 or 18 < utc_hour <= 21:
        return 260.0
    else:
        return 255.0


def find_matching_weather_file(timestamp_wms_str: str, weather_dir: str) -> str | None:
    ts_target = datetime.strptime(timestamp_wms_str, "%Y-%m-%dT%H:%M:%SZ")
    candidates = glob(os.path.join(weather_dir, "*.json"))
    best_match = None
    min_diff = None
    for path in candidates:
        try:
            fname = os.path.basename(path).replace(".json", "").replace("wetter_", "")
            ts = datetime.strptime(fname, "%Y-%m-%d_%H-%M-%S")
            if ts <= ts_target:
                diff = (ts_target - ts).total_seconds()
                if min_diff is None or diff < min_diff:
                    best_match = path
                    min_diff = diff
        except Exception:
            continue
    return best_match


def _uint8_to_bt_kelvin(bt_uint8: np.ndarray) -> np.ndarray:
    """
    Kalibriert EUMETView uint8-Pixelwerte auf Brightness Temperature in Kelvin.
    Pixelwert 0   → EUMETVIEW_BT_MAX_K (warme Oberfläche)
    Pixelwert 255 → EUMETVIEW_BT_MIN_K (hohe, kalte Wolke)
    Nodata-Pixel (<= EUMETVIEW_NODATA_PIXEL) werden auf NaN gesetzt.
    """
    bt = bt_uint8.copy().astype(np.float32)
    bt[bt <= EUMETVIEW_NODATA_PIXEL] = np.nan
    scale = (EUMETVIEW_BT_MAX_K - EUMETVIEW_BT_MIN_K) / 255.0
    bt_k = EUMETVIEW_BT_MAX_K - scale * bt
    return bt_k


# ── Haupt-API ─────────────────────────────────────────────────────────────────

def assign_cloud_top_height(
    objects: list,
    weather_data: list | None = None,
    timestamp: str | None = None,
) -> list:
    """
    Weist jedem Objekt eine Wolkenhöhe MSL zu.
    Lädt EUMETView IR108 TIFF nur wenn neuer Timestamp oder TIFF fehlt lokal.
    Bei vorhandenem TIFF (Cache-Hit) wird TIFF trotzdem verarbeitet,
    da die Objekte des aktuellen Frames noch keine Wolkenhöhe haben.
    """
    os.makedirs(SAVE_DIR, exist_ok=True)

    timestamp_wms = get_latest_wms_time()
    if not timestamp_wms:
        debug_log("[CLOUD] Kein gültiger WMS-Timestamp — cloud_top_height_msl=-1")
        log_api_call(
            service="eumetview_capabilities",
            url="GetCapabilities",
            status_code=200,
            method="GET",
            error="parser-no-timestamp",
            response_payload={"severity": "warning", "reason": "parser-no-timestamp"},
        )
        for obj in objects:
            obj["cloud_top_height_msl"] = -1.0
            obj["cloud_height_missing"] = 1.0
        return objects

    timestamp_file = wms_to_filename_timestamp(timestamp_wms)
    pipeline_ts    = timestamp if timestamp else timestamp_file
    tif_path = os.path.join(
        SAVE_DIR,
        f"ir108_{timestamp_file.replace('-', '').replace('_', '')}.tif",
    )
    json_path = os.path.join(SAVE_DIR, f"cloud_height_{pipeline_ts}.json")

    # ── Download: nur wenn neuer Timestamp ODER TIFF fehlt lokal ─────────────
    need_download = (read_last_timestamp() != timestamp_wms) or (
        not os.path.exists(tif_path)
    )

    if need_download:
        tif_url = build_tiff_url(timestamp_wms)
        debug_log(f"[CLOUD] Lade neues TIFF: {tif_url}")
        try:
            import time as _t_wms_tiff
            _t0_wms_tiff = _t_wms_tiff.monotonic()
            from http_retry import retry_get
            r = retry_get(tif_url, service="EUMETView-WMS-TIFF",
                          breaker_service="eumetview_wms", timeout=20)  # B154
            _dur_ms = (_t_wms_tiff.monotonic() - _t0_wms_tiff) * 1000
            _ts_str = timestamp_file.replace("-", "").replace("_", "")
            _tif_save = os.path.join(SAVE_DIR, f"ir108_{_ts_str}.tif") if "r" in dir() else None
            log_http_response(
                service="eumetview_wms",
                method="GET",
                response=r,
                duration_ms=_dur_ms,
                saved_to=_tif_save,
            )
            r.raise_for_status()

            # WMS ServiceException kommt als "200 OK + XML"
            content_type = r.headers.get("Content-Type", "")
            if "tiff" not in content_type.lower() and "image" not in content_type.lower():
                debug_log(f"[CLOUD] WMS lieferte kein Bild (Content-Type={content_type})")
                debug_log(f"[CLOUD] Server-Antwort: {r.text[:300]}")
                log_api_failure(
                    "EUMETView-WMS",
                    tif_url,
                    f"Content-Type={content_type}",
                    fallback_used=True,
                )
                for obj in objects:
                    obj["cloud_top_height_msl"] = -1.0
                    obj["cloud_height_missing"] = 1.0
                return objects

            with open(tif_path, "wb") as f:
                f.write(r.content)
            write_last_timestamp(timestamp_wms)
            debug_log(f"[CLOUD] TIFF gespeichert: {tif_path}")

        except Exception as e:
            debug_log(f"[CLOUD] TIFF-Download fehlgeschlagen: {e}")
            log_api_failure(
                "EUMETView-WMS", tif_url, f"{type(e).__name__}: {e}", fallback_used=True
            )
            for obj in objects:
                obj["cloud_top_height_msl"] = -1.0
                obj["cloud_height_missing"] = 1.0
            return objects
    else:
        # Kein neuer Download, aber TIFF muss trotzdem verarbeitet werden —
        # die Objekte dieses Frames sind neu und haben noch keine Höhe.
        debug_log("[CLOUD] Kein neues TIFF (Timestamp unverändert) – verarbeite vorhandenes TIFF")

    if not os.path.exists(tif_path):
        debug_log(f"[CLOUD] TIFF nach Download nicht vorhanden: {tif_path}")
        log_api_failure(
            "EUMETView-WMS", tif_path, "tiff-missing-after-download", fallback_used=True
        )
        for obj in objects:
            obj["cloud_top_height_msl"] = -1.0
            obj["cloud_height_missing"] = 1.0
        return objects

    # ── Oberflächentemperatur ermitteln ───────────────────────────────────────
    weather_path = find_matching_weather_file(
        timestamp_wms, SAVE_PATHS["weather"].rstrip("/")
    )
    T_surface = 290.15
    altitude_m = 600.0

    if weather_data:
        try:
            stations = weather_data if isinstance(weather_data, list) else [weather_data]
            tl_values = [
                float(s["TL"])
                for s in stations
                if isinstance(s, dict) and s.get("TL") not in (None, 0, "0")
            ]
            if tl_values:
                T_surface = sum(tl_values) / len(tl_values) + 273.15
        except Exception as e:
            debug_log(f"[CLOUD] Wetterdaten (Parameter) konnten nicht gelesen werden: {e}")
    elif weather_path:
        try:
            with open(weather_path) as f:
                raw = json.load(f)
            stations = raw if isinstance(raw, list) else [raw]
            tl_values = [
                float(s["TL"])
                for s in stations
                if isinstance(s, dict) and s.get("TL") not in (None, 0, "0")
            ]
            if tl_values:
                T_surface = sum(tl_values) / len(tl_values) + 273.15
            altitude_m = 600.0
        except Exception as e:
            debug_log(f"[CLOUD] Wetterdaten-Parsing fehlgeschlagen: {e}")
    else:
        debug_log("[CLOUD] Keine passende Wetterdatei gefunden — Standardwerte.")

    # ── TIFF verarbeiten ──────────────────────────────────────────────────────
    if not HAS_RASTERIO:
        debug_log("[CLOUD] rasterio nicht verfügbar – cloud_top_height_msl=-1")
        for obj in objects:
            obj["cloud_top_height_msl"] = -1.0
            obj["cloud_height_missing"] = 1.0
        return objects

    try:
        with rasterio.open(tif_path) as src:
            raster_rows, raster_cols = src.height, src.width
            band = src.read(1)
            utc_hour = datetime.utcnow().hour
            nan_threshold = get_adaptive_nan_threshold(utc_hour)

            # dtype-adaptiver Pfad: EUMETView liefert je nach Konfiguration
            # entweder uint8-Visualisierungsbild (Pixelwert 0–255) oder
            # float32-Physikwerte direkt in Kelvin (~180–330 K).
            debug_log(
                f"[CLOUD] TIFF: dtype={band.dtype}, shape={band.shape}, "
                f"min={float(band.min()):.2f}, max={float(band.max()):.2f}, "
                f"zeros={int((band == 0).sum())}, nan_threshold={nan_threshold}"
            )

            if np.issubdtype(band.dtype, np.floating):
                # Float32-Physikwerte direkt in Kelvin
                bt_k = band.astype(np.float32)
                # Ungültige Werte (0 oder extrem) maskieren
                bt_k[bt_k <= 0] = np.nan
                bt_k[bt_k > 400] = np.nan
                debug_log(f"[CLOUD] Float32-Modus: {np.nanmean(bt_k):.1f} K Mittel")
            else:
                # uint8-Visualisierungsbild → Kalibrierung via config
                bt_k = _uint8_to_bt_kelvin(band)
                debug_log(
                    f"[CLOUD] uint8-Modus: bt_k min={float(np.nanmin(bt_k)):.1f} K, "
                    f"max={float(np.nanmax(bt_k)):.1f} K, "
                    f"nan_threshold={nan_threshold} K"
                )
            lapse_rate = runtime_config.get("LAPSE_RATE", 6.5) / 1000.0  # K/m
            height_msl = (T_surface - bt_k) / lapse_rate + altitude_m

            # Werte unter NaN-Threshold → NaN (wolkenfrei oder Nodata)
            height_msl[bt_k > nan_threshold] = float("nan")

            # JSON-Snapshot speichern
            try:
                import json as _json
                snap = {
                    "timestamp_wms": timestamp_wms,
                    "pipeline_ts":   pipeline_ts,
                    "T_surface_K":   round(T_surface, 2),
                    "altitude_m":    altitude_m,
                    "nan_threshold": nan_threshold,
                }
                with open(json_path, "w") as jf:
                    _json.dump(snap, jf)
                debug_log(f"[CLOUD] JSON-Snapshot gespeichert: {json_path}")
            except Exception:
                pass

            # Höhen-Alarm-Schwellen (runtime-überschreibbar). Einmal pro Frame lesen.
            from config import (
                CLOUD_HEIGHT_ALERT_THRESHOLD_M as _CHA_THR_DEF,
                CLOUD_HEIGHT_ALERT_MIN_CORE_RATIO as _CHA_CORE_DEF,
            )
            _alert_thr_m = float(
                runtime_config.get("CLOUD_HEIGHT_ALERT_THRESHOLD_M", _CHA_THR_DEF)
            )
            _alert_min_core = float(
                runtime_config.get("CLOUD_HEIGHT_ALERT_MIN_CORE_RATIO", _CHA_CORE_DEF)
            )
            assigned = 0
            for obj in objects:
                lat, lon = obj.get("lat"), obj.get("lon")
                if lat is None or lon is None:
                    obj["cloud_top_height_msl"] = -1.0
                    obj["cloud_height_missing"] = 1.0
                    continue
                try:
                    row, col = rowcol(src.transform, lon, lat)
                    if row < 0 or col < 0 or row >= raster_rows or col >= raster_cols:
                        debug_log(
                            f"[CLOUD] Koordinate lat={lat},lon={lon} außerhalb Raster "
                            f"(row={row},col={col},shape={raster_rows}x{raster_cols})"
                        )
                        obj["cloud_top_height_msl"] = -1.0
                        obj["cloud_height_missing"] = 1.0
                        continue

                    value   = height_msl[row, col]
                    bt_val  = bt_k[row, col]

                    if np.isnan(value):
                        if np.isnan(bt_val):
                            # bt_k war Nodata/korrupt → fehlende Satellitendaten
                            obj["cloud_top_height_msl"] = -1.0
                            obj["cloud_height_missing"] = 1.0
                        else:
                            # bt_k > nan_threshold → Satellit sieht keine kalte Wolke.
                            # Bei erkannter Gewitterzelle (core_ratio > 0) ist das
                            # ein Widerspruch (MSG-Scan zu alt, Koordinatenversatz,
                            # frisch entstehende Konvektion) → Datenfehler, nicht wolkenfrei.
                            is_convective = float(obj.get("core_ratio", 0.0)) > 0.0
                            obj["cloud_top_height_msl"] = -1.0
                            obj["cloud_height_missing"] = 1.0 if is_convective else 0.0
                            if is_convective:
                                debug_log(
                                    f"[CLOUD] Widerspruch: Zelle {obj.get('id','?')} "
                                    f"core_ratio={obj.get('core_ratio',0):.2f} aber "
                                    f"bt_k={float(bt_val):.1f} K > threshold={nan_threshold} K"
                                    f" → cloud_height_missing=1"
                                )
                    else:
                        obj["cloud_top_height_msl"]       = round(float(value), 1)
                        obj["cloud_height_missing"]        = 0.0
                        obj["cloud_top_height_timestamp"] = timestamp_file
                        # CB-only: Alarm nur bei großer Höhe UND konvektivem Kern.
                        # Hohe Wolken ohne Kern (Cirren/Amboss/Stratiform) lösen NICHT aus.
                        _is_cb = float(obj.get("core_ratio", 0.0)) >= _alert_min_core
                        obj["cloud_top_alert"] = (
                            1.0 if (float(value) >= _alert_thr_m and _is_cb) else 0.0
                        )
                        assigned += 1

                except Exception as ex:
                    debug_log(f"[CLOUD] rowcol-Fehler lat={lat} lon={lon}: {ex}")
                    obj["cloud_top_height_msl"] = -1.0
                    obj["cloud_height_missing"] = 1.0

            debug_log(f"[CLOUD] Wolkenhöhe zugewiesen: {assigned}/{len(objects)} Objekte")

    except Exception as e:
        debug_log(f"[CLOUD] TIFF-Verarbeitung fehlgeschlagen: {e}")
        log_api_failure(
            "EUMETView-WMS-TIFF", tif_path, f"{type(e).__name__}: {e}", fallback_used=True
        )
        for obj in objects:
            obj["cloud_top_height_msl"] = -1.0
            obj["cloud_height_missing"] = 1.0

    write_last_timestamp(timestamp_wms)
    return objects


def fetch_cloud_height_for_points(latlons: list) -> dict:
    """
    Gibt für eine Liste von (lat, lon) Tupeln die Wolkenhöhe MSL in Meter zurück.
    Nutzt das aktuell gecachte EUMETView IR108 TIFF (kein neuer Download wenn
    TIFF aktuell ist). Wird vom Atmospheric Snapshot aufgerufen.

    Rückgabe: {(lat, lon): cloud_height_m} — 0.0 wenn keine Wolke erkannt.
    """
    if not HAS_RASTERIO or not HAS_NUMPY:
        return {ll: 0.0 for ll in latlons}

    # Aktuelles TIFF suchen (neuestes in SAVE_DIR)
    tif_files = sorted(glob(os.path.join(SAVE_DIR, "ir108_*.tif")))
    if not tif_files:
        debug_log("[CLOUD-GRID] Kein TIFF vorhanden — fetch_cloud_height_for_points gibt 0 zurück")
        return {ll: 0.0 for ll in latlons}

    tif_path = tif_files[-1]
    result = {}

    try:
        with rasterio.open(tif_path) as src:
            band = src.read(1)
            utc_hour = datetime.utcnow().hour
            nan_threshold = get_adaptive_nan_threshold(utc_hour)
            T_surface = 290.15   # Fallback
            altitude_m = 600.0

            for (lat, lon) in latlons:
                try:
                    row, col = rowcol(src.transform, lon, lat)
                    if not (0 <= row < src.height and 0 <= col < src.width):
                        result[(lat, lon)] = 0.0
                        continue

                    raw = band[row, col]

                    # uint8 vs float32 Pfad (identisch zu assign_cloud_top_height)
                    if band.dtype == np.float32 or band.dtype == np.float64:
                        bt_k = float(raw)
                        if np.isnan(bt_k) or bt_k <= 0 or bt_k > nan_threshold:
                            result[(lat, lon)] = 0.0
                            continue
                        height_m = ((T_surface - bt_k) / (LAPSE_RATE / 1000.0)) + altitude_m
                    else:
                        pixel = int(raw)
                        if pixel <= EUMETVIEW_NODATA_PIXEL:
                            result[(lat, lon)] = 0.0
                            continue
                        bt_k = EUMETVIEW_BT_MAX_K - ((EUMETVIEW_BT_MAX_K - EUMETVIEW_BT_MIN_K) / 255.0) * pixel
                        if bt_k > nan_threshold:
                            result[(lat, lon)] = 0.0
                            continue
                        height_m = ((T_surface - bt_k) / (LAPSE_RATE / 1000.0)) + altitude_m

                    result[(lat, lon)] = max(0.0, round(float(height_m), 0))
                except Exception:
                    result[(lat, lon)] = 0.0

    except Exception as exc:
        debug_log(f"[CLOUD-GRID] TIFF-Verarbeitung fehlgeschlagen: {exc}")
        return {ll: 0.0 for ll in latlons}

    debug_log(f"[CLOUD-GRID] Wolkenhöhe für {len(latlons)} Punkte berechnet aus {os.path.basename(tif_path)}")
    return result
