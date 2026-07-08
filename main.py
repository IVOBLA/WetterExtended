# main.py

import time
import os
import cv2
import json
import debug_utils

from radar_download import download_kmz
from object_tracking import detect_and_track_objects
from weather_api import get_weather_data
from prediction import predict_positions
import size_regressor as _size_reg_mod
from kmz_export import save_forecast_as_kmz
from visualize_radar import create_visualized_radar
from movement_gif import create_movement_gif
from upload_utilities import upload_file_ftp
from debug_utils import debug_log
from fetch_700hpa_wind_per_object_slim import fetch_and_assign_700hpa_wind
from assign_cape_from_forecast import assign_cape
from geo_utils import get_roi_from_bbox, kml_bounds
from config import (BBOX_KAERNTEN_EXTENDED, SAVE_PATHS, LIVE_LOOP_INTERVAL_S,
                    LOOP_INTERVAL_CELLS_S, LOOP_INTERVAL_NO_CELLS_S,
                    LOOP_INTERVAL_NACHBEOBACHTUNG_S)
from cloud_height_from_eumetview import assign_cloud_top_height
from optical_flow_features import assign_optical_flow_to_objects
from radar_frame_selection import remember_valid_radar_path, select_optflow_prev_radar_path
from fetch_arome_openmeteo import assign_arome_to_objects
from fetch_synoptic_features import assign_synoptic_features
from orographic_module import assign_orographic_scores
from fetch_openmeteo_extended import assign_extended_openmeteo
from fetch_geosphere_nowcast import assign_nowcast_to_objects
from compute_convective_indices import assign_convective_indices
from fetch_tawes_gust import fetch_tawes_stations, max_gust_near
from ir_cell_detection import detect_ir_cells
from ir_cell_tracking import mark_radar_matched_tracks, update_ir_tracking
from climatology_features import enrich_objects as _clim_enrich
from feature_schema import attach_schema_metadata
import math as _math_main
import runtime_config
from locations_check import annotate_locations
from risk_watch import risk_watch_active
from config import (HAIL_WARN_THRESHOLD, STATIONARY_RISK_MARKER_THRESHOLD,
                    GUST_WARN_KMH, HEAVY_RAIN_WARN_MM_PER_H)

_ROI_CACHE = None
_RISK_ALERT_LOG = os.path.join(
    SAVE_PATHS.get("evaluation", "train_data/evaluation"),
    "risk_alert_sent.json"
)



def _parse_ir_tiff_observation_timestamp(tif_path: str) -> tuple[str | None, str]:
    from datetime import datetime as _dt
    meta_path = os.path.splitext(tif_path)[0] + ".json"
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f) or {}
            ts = meta.get("observation_timestamp") or meta.get("wms_timestamp")
            if ts:
                return ts, str(meta.get("timestamp_source") or "wms_time_dimension")
        except Exception as exc:
            debug_log(f"[IR-PIPE] IR108-Metadaten unlesbar: {exc}")
    import re
    m = re.search(r"ir108_(\d{14})\.tif$", os.path.basename(tif_path))
    if m:
        try:
            return _dt.strptime(m.group(1), "%Y%m%d%H%M%S").strftime("%Y-%m-%dT%H:%M:%SZ"), "tiff_filename"
        except ValueError:
            pass
    try:
        return _dt.utcfromtimestamp(os.path.getmtime(tif_path)).strftime("%Y-%m-%dT%H:%M:%SZ"), "fallback_file_mtime_untrusted"
    except OSError:
        return None, "missing"


def _latest_ir_tiff_fresh(max_age_min: float | None = None) -> bool:
    import glob
    from datetime import datetime as _dt
    cloud_dir = SAVE_PATHS.get("cloud", "train_data/cloud/")
    files = sorted(glob.glob(os.path.join(cloud_dir, "ir108_*.tif")))
    if not files:
        return False
    max_age = float(max_age_min if max_age_min is not None else runtime_config.get("IR_MAX_DATA_AGE_MIN", 25.0))
    ts, source = _parse_ir_tiff_observation_timestamp(files[-1])
    if not ts:
        return False
    try:
        dt = _dt.strptime(str(ts).replace("+00:00", "Z"), "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    age_min = (_dt.utcnow() - dt).total_seconds() / 60.0
    if source == "fallback_file_mtime_untrusted":
        debug_log("[IR-PIPE] Freshness nutzt unsicheren mtime-Fallback")
    return age_min <= max_age


def run_ir_precursor_pipeline(timestamp=None, weather_data=None, allow_cached=True, reason="loop"):
    """Radar-unabhängige IR108-Frühphasenpipeline ohne zusätzliche Fremdrequests."""
    if not bool(runtime_config.get("IR_WATCH_ENABLED", True)):
        debug_log(f"[IR-PIPE] deaktiviert (reason={reason})")
        return []
    if not _latest_ir_tiff_fresh():
        debug_log(f"[IR-PIPE] kein frisches IR108-TIFF vorhanden (reason={reason})")
        return []
    if timestamp is None:
        import glob
        from datetime import datetime as _dt
        cloud_dir = SAVE_PATHS.get("cloud", "train_data/cloud/")
        files = sorted(glob.glob(os.path.join(cloud_dir, "ir108_*.tif")))
        obs_ts, _src = _parse_ir_tiff_observation_timestamp(files[-1]) if files else (None, "missing")
        try:
            timestamp = _dt.strptime(str(obs_ts).replace("+00:00", "Z"), "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%d_%H-%M-%S")
        except Exception:
            timestamp = _dt.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
    try:
        cells = detect_ir_cells(timestamp=timestamp, weather_data=weather_data)
        tracks = update_ir_tracking(cells, timestamp)
        debug_log(f"[IR-PIPE] reason={reason}: {len(cells)} Detektionen, {len(tracks)} aktive Tracks")
        return tracks
    except Exception as exc:
        debug_log(f"[IR-PIPE] Fehler reason={reason}: {type(exc).__name__}: {exc}")
        return []


def _legacy_ir_radar_distance_match(objects, ir_tracks):
    """Legacy-Fallback: nächster IR-Track innerhalb 40 km (B109-kompatibel)."""
    from cell_lineage import haversine_km
    match_km = float(runtime_config.get("IR_RADAR_MATCH_MAX_KM", 40.0))
    matched_ir_ids = set()
    for obj in objects or []:
        obj_lat = obj.get("lat", 0.0); obj_lon = obj.get("lon", 0.0)
        best_dist = float("inf"); best_ir = None
        for ir in ir_tracks or []:
            try:
                d = haversine_km(float(obj_lat), float(obj_lon), float(ir["lat"]), float(ir["lon"]))
            except Exception:
                continue
            if d < best_dist:
                best_dist = d; best_ir = ir
        if best_ir is not None and best_dist <= match_km:
            obj["cell_id"] = best_ir.get("cell_id", obj.get("cell_id"))
            obj["ir_match_id"] = best_ir.get("ir_id")
            obj["ir_track_id"] = best_ir.get("ir_track_id") or best_ir.get("ir_id")
            obj["ir_status"] = "radar_confirmed"
            obj["ir_radar_confirmed"] = True
            obj["ir_is_potential_new_cell"] = False
            obj["ir_display_as_precursor"] = False
            obj["ir_area_growth_km2_per_min"] = best_ir.get("area_growth_km2_per_min", 0.0)
            obj["ir_cloud_height_trend_m_per_min"] = best_ir.get("cloud_height_trend_m_per_min", 0.0)
            for key in ("bt_min_k", "bt_mean_k", "bt_trend_k_per_min", "cloud_age_min", "anvil_extension_km", "overshooting_top"):
                obj[key] = best_ir.get(key, obj.get(key, 0.0))
            obj["ir_only_precursor"] = 0.0
            best_ir.update({"radar_track_id": obj.get("id"), "status": "radar_confirmed", "radar_confirmed": True, "is_potential_new_cell": False, "display_as_precursor": False, "ir_only_precursor": 0.0})
            matched_ir_ids.add(best_ir.get("ir_track_id") or best_ir.get("ir_id"))
        else:
            obj.setdefault("ir_match_id", None)
            obj.setdefault("bt_min_k", 0.0)
            obj.setdefault("bt_mean_k", 0.0)
            obj.setdefault("bt_trend_k_per_min", 0.0)
            obj.setdefault("cloud_age_min", 0.0)
            obj.setdefault("anvil_extension_km", 0.0)
            obj.setdefault("overshooting_top", 0.0)
            obj.setdefault("ir_only_precursor", 0.0)
    return objects or [], ir_tracks or [], matched_ir_ids


def _score_match_ir_radar_lineage(objects, ir_tracks, *, timestamp=None, weather_data=None):
    from cell_lineage import update_cell_lineage
    return update_cell_lineage(
        radar_objects=objects,
        ir_tracks=ir_tracks,
        timestamp=timestamp,
        weather_context=weather_data,
    )

def _risk_alert_check(timestamp: str) -> None:
    import json as _j
    from datetime import datetime as _dt, timezone as _tz
    _RISK_COOLDOWN_S = 7200          # 2 Stunden zwischen Risk-Alarmen pro Ort
    _now_epoch = _dt.now(_tz.utc).timestamp()
    _sent = {}
    try:
        if os.path.exists(_RISK_ALERT_LOG):
            with open(_RISK_ALERT_LOG, encoding="utf-8") as _f:
                _sent = _j.load(_f)
    except Exception:
        _sent = {}
    _locs = runtime_config.get("LOCATIONS_WATCHLIST", [])
    _locs_with_email = [l for l in _locs if l.get("email", "").strip()]
    if not _locs_with_email:
        return
    # B262: Retry mit Backoff — 2 Versuche mit 1 s Pause bei temporärem Timeout
    import time as _time
    import requests as _req
    _grid = None
    _RISK_GRID_URL = "http://127.0.0.1:5000/api/risk_grid"
    for _attempt in range(2):
        try:
            _resp = _req.get(_RISK_GRID_URL, timeout=5)
            if _resp.status_code == 200:
                _grid = _resp.json().get("cells", [])
            break
        except Exception as _exc:
            if _attempt == 0:
                debug_log(f"[RISK-ALERT] Risk-Grid Versuch 1 fehlgeschlagen: {_exc} — retry in 1 s")
                _time.sleep(1)
            else:
                debug_log(f"[RISK-ALERT] Risk-Grid nicht erreichbar (2 Versuche): {_exc}")
    if _grid is None:
        return
    _changed = False
    for loc in _locs_with_email:
        loc_name = loc.get("name", "?")
        loc_lat = float(loc.get("lat", 0))
        loc_lon = float(loc.get("lon", 0))
        email  = loc.get("email",    "").strip()
        wa_str = loc.get("whatsapp", "").strip()
        # Epoch-basierter Cooldown (rückwärtskompatibel: alter Datumsstring
        # → float() schlägt fehl → epoch=0 → Cooldown abgelaufen → Alarm ok)
        try:
            _last_sent_epoch = float(_sent.get(loc_name, 0))
        except (TypeError, ValueError):
            _last_sent_epoch = 0.0
        if _last_sent_epoch > _now_epoch - _RISK_COOLDOWN_S:
            debug_log(
                f"[RISK-ALERT] {loc_name}: Cooldown aktiv — "
                f"naechster Alarm in "
                f"{int((_last_sent_epoch + _RISK_COOLDOWN_S - _now_epoch) / 60)} min."
            )
            continue
        best_cell = min(_grid, key=lambda c: abs(c["lat"] - loc_lat) + abs(c["lon"] - loc_lon), default=None)
        if not best_cell or best_cell.get("risk", 0) < 3:
            continue
        info = best_cell.get("info", {})
        try:
            from email_notifier import send_risk_alert_email
            ok = send_risk_alert_email(location_name=loc_name, dominant=info.get("dominant", "atm"), details=info, recipient=email)
            if ok:
                _sent[loc_name] = _now_epoch     # Epoch statt Datum
                _changed = True
                debug_log(f"[RISK-ALERT] ✅ Alarm gesendet: {loc_name} → {email}")
            else:
                debug_log(f"[RISK-ALERT] ❌ E-Mail fehlgeschlagen: {loc_name}")
        except Exception as _exc:
            debug_log(f"[RISK-ALERT] Fehler: {_exc}")
        # ── WhatsApp: Risiko-Stufe-3-Alarm (Tages-Cooldown via _RISK_ALERT_LOG)
        if wa_str:
            try:
                from whatsapp_notifier import send_risk_alert_wa
                send_risk_alert_wa(
                    location_name=loc_name,
                    dominant=info.get("dominant", "atm"),
                    details=info,
                    wa_str=wa_str,
                )
            except Exception as _wa_exc:
                debug_log(f"[WA] Risiko-Alarm Fehler: {_wa_exc}")
    if _changed:
        try:
            os.makedirs(os.path.dirname(_RISK_ALERT_LOG), exist_ok=True)
            with open(_RISK_ALERT_LOG, "w", encoding="utf-8") as _f:
                _j.dump(_sent, _f, indent=2, ensure_ascii=False)
        except Exception as _se:
            debug_log(f"[RISK-ALERT] Cooldown speichern fehlgeschlagen: {_se}")

def _count_lightning_near(lat: float, lon: float,
                          lightning_data: list, radius_km: float = 10.0) -> int:
    """
    Zählt Blitze im radius_km-Umkreis (echter Kreis via Haversine-Distanz).
    Vorfilter über lat/lon-Box spart Rechenzeit; die finale Prüfung nutzt die
    Großkreis-Distanz, sodass nur Blitze INNERHALB des Kreises gezählt werden.
    """
    if not lightning_data:
        return 0
    # Grober Box-Vorfilter (schließt offensichtlich entfernte Blitze schnell aus)
    lat_box = radius_km / 111.0
    lon_box = radius_km / (111.0 * abs(_math_main.cos(_math_main.radians(lat))) + 1e-9)
    _r_lat = _math_main.radians(lat)
    count = 0
    for bolt in lightning_data:
        blat = bolt.get("lat") or bolt.get("y")
        blon = bolt.get("lon") or bolt.get("x")
        if blat is None or blon is None:
            continue
        blat = float(blat)
        blon = float(blon)
        # 1. Box-Vorfilter
        if abs(blat - lat) > lat_box or abs(blon - lon) > lon_box:
            continue
        # 2. Exakte Haversine-Distanz (km)
        dlat = _math_main.radians(blat - lat)
        dlon = _math_main.radians(blon - lon)
        a = (_math_main.sin(dlat / 2) ** 2
             + _math_main.cos(_r_lat) * _math_main.cos(_math_main.radians(blat))
             * _math_main.sin(dlon / 2) ** 2)
        dist_km = 2 * 6371.0 * _math_main.asin(min(1.0, _math_main.sqrt(a)))
        if dist_km <= radius_km:
            count += 1
    return count


def _compute_hail_prob(obj: dict) -> float:
    """
    Hagelwahrscheinlichkeit 0.0–1.0 aus vorhandenen Features (F06/F43).

    Formel: hail_prob = core_factor * cape_factor * height_factor
      core_factor  : core_ratio (0-1) — kompakter Kern = Hagelindiz
      cape_factor  : CAPE / 1500 J/kg, max 1.0 — viel Energie = Hagelmöglich
      height_factor: 1.0 wenn Gefriergrenze < 3000 m MSL,
                     linear 0.0 bei 4500 m (hohe Gefriergrenze = kein Hagel)
    """
    core_ratio = float(obj.get("core_ratio", 0.0))
    cape       = float(obj.get("cape", 0.0))
    fl_height  = float(obj.get("arome_fl_height", 4000.0))  # m MSL

    core_factor  = min(core_ratio, 1.0)
    cape_factor  = min(cape / 1500.0, 1.0) if cape > 0 else 0.0
    height_factor = 1.0 if fl_height <= 3000 else max(0.0, (4500.0 - fl_height) / 1500.0)

    return round(core_factor * cape_factor * height_factor, 3)


def _compute_hail_warning(obj: dict) -> tuple:
    """
    B324: Kombiniert die heuristische Kernformel (_compute_hail_prob, bleibt
    unveraendert als ML_CELL_FEATURES-Feld "hail_prob" erhalten) mit dem bereits
    vorhandenen SHIP-basierten "hail_prob2" (compute_convective_indices.py) zu
    einer robusteren operativen Warnentscheidung.

    Ursache B324: _compute_hail_prob multipliziert core_factor * cape_factor *
    height_factor. Drei Faktoren <= 1.0 multipliziert unterschaetzen die
    Hagelwahrscheinlichkeit systematisch, sobald auch nur einer davon
    mittelmaessig ist (z.B. Gefriergrenze > 3000 m, in Kaernten im Sommer der
    Normalfall) - hail_prob erreichte HAIL_WARN_THRESHOLD dadurch faktisch nie.

    hail_prob2 ist laut eigenem Docstring in compute_convective_indices.py
    bereits "kompatibel mit HAIL_WARN_THRESHOLD" konzipiert (SHIP + Lapse +
    Shear + Lightning-Jump + Core-Ratio, additiv gewichtet), wurde bisher
    aber nirgends fuer die Warnentscheidung ausgewertet.

    hail_prob (ML-Feature) bleibt exakt wie zuvor berechnet, damit bereits
    trainierte Modelle kein Retraining benoetigen. hail_prob_effective ist
    ein neues, zusaetzliches Feld ausschliesslich fuer Warnentscheidung und
    Kartenanzeige.

    Rueckgabe: (hail_prob, hail_prob_effective, hail_warning)
    """
    hail_prob = _compute_hail_prob(obj)
    hail_prob2 = float(obj.get("hail_prob2", 0.0) or 0.0)
    hail_prob_effective = round(max(hail_prob, hail_prob2), 3)
    hail_warning = bool(hail_prob_effective >= HAIL_WARN_THRESHOLD)
    return hail_prob, hail_prob_effective, hail_warning


def _suppress_inactive_rain_warning_badges(obj: dict) -> dict:
    """Entfernt Karten-Warnmarker fuer still nachverfolgte Regenreste."""
    if obj.get("tracking_state") == "inactive_rain" or obj.get("silent_tracking") is True:
        obj["hail_warning"] = False
        obj["stationary_marker"] = False
        obj["hail_prob"] = 0.0
        obj["hail_prob_effective"] = 0.0
        obj["stationary_risk"] = 0.0
    return obj


def _compute_wind_shear(obj: dict) -> tuple:
    """
    Windscherung zwischen Boden (10m) und 700 hPa (ca. 3000m) (F16).
    Rückgabe: (wind_shear_speed_kmh, wind_shear_dir_cos, wind_shear_dir_sin)
    """
    speed_700 = float(obj.get("wind_speed_700hPa", 0.0))
    dir_cos_700 = float(obj.get("wind_dir_cos", 0.0))
    dir_sin_700 = float(obj.get("wind_dir_sin", 0.0))
    speed_10m = float(obj.get("arome_ff10m", 0.0))
    dir_cos_10m = float(obj.get("arome_dd_cos", 0.0))
    dir_sin_10m = float(obj.get("arome_dd_sin", 0.0))

    vx_700 = speed_700 * dir_cos_700
    vy_700 = speed_700 * dir_sin_700
    vx_10m = speed_10m * dir_cos_10m
    vy_10m = speed_10m * dir_sin_10m

    dvx = vx_700 - vx_10m
    dvy = vy_700 - vy_10m
    shear_speed = _math_main.hypot(dvx, dvy)
    angle = _math_main.atan2(dvy, dvx) if shear_speed > 0 else 0.0
    return (
        round(shear_speed, 2),
        round(_math_main.cos(angle), 4),
        round(_math_main.sin(angle), 4),
    )


def _apply_hydro_productive_run(objects, timestamp):
    """Wendet Hydro-Impact im Produktivlauf an, ohne Requests bei deaktiviertem Hydro."""
    from hydro_fetch import hydro_enabled
    if hydro_enabled(True):
        from hydro_fetch import fetch_hydro_live
        from impact_evaluation import evaluate_impact
        fetch_hydro_live(force=False)
        evaluate_impact(objects, timestamp)
    else:
        for _obj in objects:
            _obj.setdefault("impact", {})["hydro"] = False
            _obj["impact"]["hydro_status"] = "hydro_disabled"


def main_loop():
    image_path = "data/latest.png"

    _prev_radar_path = None
    _last_valid_radar_path = None
    _prev_location_hit_names: set = set()  # F47: Auto-Entwarnung
    # B121: _last_cells_active_ts aus Snapshot initialisieren damit nach einem
    # Neustart der adaptive Loop nicht sofort in den 900s-Ast fällt, obwohl kurz
    # vorher Zellen aktiv waren.
    # load_tracking_snapshot() füllt tracking_memory und gibt das Snapshot-Alter
    # zurück. Wenn Alter < INACTIVE_CELL_TRACK_DURATION_S → Zellen waren kürzlich
    # aktiv → last_cells_active_ts auf (jetzt - Alter) setzen.
    try:
        from object_tracking import load_tracking_snapshot as _load_snap
        _snap_age_s = _load_snap()
        if _snap_age_s < float("inf"):
            _last_cells_active_ts: float | None = time.time() - _snap_age_s
            debug_log(
                f"[SNAPSHOT] _last_cells_active_ts aus Snapshot gesetzt "
                f"(Alter: {_snap_age_s:.0f}s)"
            )
        else:
            _last_cells_active_ts: float | None = None
    except Exception as _snap_exc:
        debug_log(f"[SNAPSHOT] Initialisierung fehlgeschlagen: {_snap_exc}")
        _last_cells_active_ts: float | None = None
    # 2-Frame-Bestätigung für unsichere Vorhersagen (kinematic forecast_mode):
    # Orte die schon 1× getroffen wurden aber noch auf Frame 2 warten.
    _location_warn_pending: dict = {}   # {loc_name: frame_count}
    # Orte für die in diesem Session bereits eine Warnung gesendet wurde
    # (Entwarnung nur senden wenn vorher eine Warnung gesandt wurde).
    _location_warned: set = set()
    # B98: {loc_name: set(cell_ids)} — je Zelle wird nur einmal gewarnt.
    # Wird bei Entwarnung geleert, sodass eine zurückkehrende/neue Zelle
    # erneut auslöst.
    _warned_cells: dict = {}

    while True:
        runtime_config.reload_overrides()
        global _ROI_CACHE
        _bbox = runtime_config.get("BBOX_KAERNTEN_EXTENDED", BBOX_KAERNTEN_EXTENDED)
        _ROI_CACHE = get_roi_from_bbox(_bbox)
        debug_log("Neuer Zyklus gestartet...")
        radar_ok = download_kmz()

        if not radar_ok:
            # B177: Skip-Grund differenzieren (Diagnose von Track-Abrissen).
            try:
                from radar_download import last_skip_reason as _radar_skip_reason
                _skip_reason = _radar_skip_reason()
            except Exception:
                _skip_reason = None
            if _skip_reason in (None, "not_new"):
                debug_log("[SKIP] Radarbild nicht neu (304/identischer Inhalt) → nächster Zyklus.")
            elif _skip_reason == "circuit_open":
                debug_log("[SKIP] Radar-Circuit offen → nächster Zyklus.")
            else:
                debug_log(f"[SKIP] Radarbild ungültig ({_skip_reason}) → nächster Zyklus.")
            _ir_tracks = run_ir_precursor_pipeline(reason=f"radar_skip:{_skip_reason or 'not_new'}")
            # 3-Stufen-Intervall auch im Skip-Pfad (ARSO liefert kein neues Bild):
            #   < 5 min seit letzter Zelle  → 2 min  (Zellen kürzlich aktiv)
            #   < 120 min seit letzter Zelle → 5 min  (Nachbeobachtung)
            #   ≥ 120 min / nie             → 15 min (Ruhe)
            from config import NO_CELLS_SLOW_INTERVAL_TIMEOUT_S as _NCST_SKIP
            _timeout_skip = float(runtime_config.get(
                "NO_CELLS_SLOW_INTERVAL_TIMEOUT_S", _NCST_SKIP
            ))
            _nb_s_skip = float(runtime_config.get(
                "LOOP_INTERVAL_NACHBEOBACHTUNG_S", LOOP_INTERVAL_NACHBEOBACHTUNG_S
            ))
            _elapsed_skip = (
                (time.time() - _last_cells_active_ts)
                if _last_cells_active_ts is not None else float("inf")
            )
            if risk_watch_active():
                _skip_sleep = runtime_config.get("LOOP_INTERVAL_CELLS_S", LOOP_INTERVAL_CELLS_S)
                debug_log(
                    f"[LOOP-SKIP] Risk-Watch aktiv (Gewitterpotenzial/CB-IR-Vorläufer) "
                    f"→ kurzer Intervall ({_skip_sleep}s)"
                )
            elif _elapsed_skip < _nb_s_skip:
                _skip_sleep = runtime_config.get("LOOP_INTERVAL_CELLS_S", LOOP_INTERVAL_CELLS_S)
                debug_log(
                    f"[LOOP-SKIP] Zellen kürzlich aktiv (vor {int(_elapsed_skip)}s) "
                    f"→ kurzer Intervall ({_skip_sleep}s)"
                )
            elif _elapsed_skip < _timeout_skip:
                _skip_sleep = int(_nb_s_skip)
                debug_log(
                    f"[LOOP-SKIP] Nachbeobachtung ({int(_elapsed_skip // 60)} min) "
                    f"→ mittlerer Intervall ({_skip_sleep}s)"
                )
            else:
                _skip_sleep = runtime_config.get(
                    "LOOP_INTERVAL_NO_CELLS_S", LOOP_INTERVAL_NO_CELLS_S
                )
                debug_log(
                    f"[LOOP-SKIP] Ruhe > {int(_timeout_skip // 60)} min "
                    f"→ langer Intervall ({_skip_sleep}s)"
                )
            time.sleep(_skip_sleep)
            continue

        image = cv2.imread(image_path) if os.path.exists(image_path) else None
        objects, timestamp = ([], None)

        weather_data = get_weather_data(include_all_stations=True)

        if image is not None:
            # Size-Regresser: Pixel-Scale — wird nach detect_and_track_objects gesetzt
            # (verarbeitetes Bild hat andere Dims/Bounds als rohe Datei)
            _km_px_x, _km_px_y = 0.51, 0.51  # Fallback überschrieben nach detect

            objects,  timestamp = detect_and_track_objects(image_path, weather_data)

            # Size-Regresser: Pixel-Scale aus VERARBEITETEM Bild (crop+upscale).
            # geo_utils.kml_bounds wird von crop_and_upscale_to_bbox() befüllt
            # und enthält img_width/img_height des aufskalierten Bildes.
            # Bounds = BBOX_KAERNTEN_EXTENDED (tatsächlicher Crop-Bereich).
            try:
                import geo_utils as _gu
                from config import BBOX_KAERNTEN_EXTENDED as _DEFAULT_BBOX_SZ
                _proc_w = _gu.kml_bounds.get("img_width")
                _proc_h = _gu.kml_bounds.get("img_height")
                _actual_bbox = runtime_config.get("BBOX_KAERNTEN_EXTENDED", _DEFAULT_BBOX_SZ)
                if _proc_w and _proc_h and _proc_w > 1 and _proc_h > 1:
                    _radar_bounds_proc = {
                        "N": float(_actual_bbox["north"]),
                        "S": float(_actual_bbox["south"]),
                        "W": float(_actual_bbox["west"]),
                        "E": float(_actual_bbox["east"]),
                    }
                    _km_px_x, _km_px_y = _size_reg_mod.pixel_scale(
                        _proc_w, _proc_h, _radar_bounds_proc
                    )
                    debug_log(
                        f"[SIZE-REG] pixel_scale: {_proc_w}×{_proc_h}px "
                        f"→ km/px_x={_km_px_x:.4f} km/px_y={_km_px_y:.4f}"
                    )
                else:
                    debug_log("[SIZE-REG] kml_bounds nicht verfügbar — Fallback 0.51")
            except Exception as _pe:
                debug_log(f"[SIZE-REG] pixel_scale Fehler: {_pe} — Fallback 0.51")
                _km_px_x, _km_px_y = 0.51, 0.51
            objects = fetch_and_assign_700hpa_wind(objects, timestamp)
            objects = assign_cape(objects, timestamp)
            # Orographische Scores nach CAPE berechnen (brauchen cape-Wert)
            objects = assign_orographic_scores(objects)
            objects = assign_cloud_top_height(objects, weather_data=weather_data, timestamp=timestamp)

            # ── Phase E: IR-Sat Pre-Convection Tracking ───────────────────────
            # Läuft nur wenn TIFF aktuell ist (cloud_height_from_eumetview hat
            # es bereits heruntergeladen — kein zusätzlicher API-Call).
            try:
                _ir_tracks = run_ir_precursor_pipeline(timestamp=timestamp, weather_data=weather_data, reason="radar_cycle")

                # IR↔Radar Lineage-Matching (1L.2): deterministisches Score-Matching
                # mit Legacy-Distanzmatching als nicht-kritischem Fallback.
                try:
                    objects, _ir_tracks, _lineage_events = _score_match_ir_radar_lineage(
                        objects, _ir_tracks, timestamp=timestamp, weather_data=weather_data
                    )
                    _matched_ir_ids = set()
                    for ev in (_lineage_events or []):
                        if ev.get("event_type") == "ir_to_radar_confirmation":
                            _matched_ir_ids.add(ev.get("ir_track_id"))
                            for _ir in _ir_tracks:
                                if (ev.get("ir_track_id") in {_ir.get("ir_track_id"), _ir.get("ir_id")}):
                                    _matched_ir_ids.add(_ir.get("ir_id"))
                    try:
                        from cell_lineage import update_split_merge_lineage
                        import object_tracking as _ot_cell_lineage
                        _split_merge_events = update_split_merge_lineage(
                            radar_objects=objects,
                            previous_objects=getattr(_ot_cell_lineage, "tracking_memory", {}),
                            timestamp=timestamp,
                        )
                        _lineage_events.extend(_split_merge_events or [])
                    except Exception as exc:
                        debug_log(f"[CELL-LINEAGE] Split/Merge-Lineage fehlgeschlagen: {exc}")
                except Exception as _lin_exc:
                    debug_log(f"[CELL-LINEAGE] Score-Matching fehlgeschlagen, nutze Legacy-IR-Matching: {_lin_exc}")
                    objects, _ir_tracks, _matched_ir_ids = _legacy_ir_radar_distance_match(objects, _ir_tracks)

                # IR-Cells OHNE Radar-Match: ir_only_precursor = 1.0
                for _ir in _ir_tracks:
                    if (_ir.get("ir_track_id") or _ir.get("ir_id")) not in _matched_ir_ids and _ir.get("ir_id") not in _matched_ir_ids:
                        _ir["status"] = "ir_precursor"
                        _ir["radar_confirmed"] = False
                        _ir["is_potential_new_cell"] = True
                        _ir["display_as_precursor"] = True
                        _ir["ir_only_precursor"] = 1.0

                # B109: Radar-Match-Status sofort persistieren damit api_risk_grid()
                # keinen veralteten IR-State liest.
                _radar_match_map = {}
                for _ir in _ir_tracks:
                    _radar_match_map[_ir.get("ir_id")] = _ir.get("radar_track_id")
                    _radar_match_map[_ir.get("ir_track_id") or _ir.get("ir_id")] = _ir.get("radar_track_id")
                mark_radar_matched_tracks(list(_matched_ir_ids), _radar_match_map)

                debug_log(f"[IR-TRACK] {len(_ir_tracks)} aktive IR-Tracks, "
                          f"{len(_matched_ir_ids)} Radar-Matches.")
            except Exception as _ir_exc:
                debug_log(f"[IR-TRACK] Pipeline-Fehler (nicht kritisch): {_ir_exc}")
                _ir_tracks = []
                for _obj in objects:
                    _obj.setdefault("ir_match_id",        None)
                    _obj.setdefault("bt_min_k",           0.0)
                    _obj.setdefault("bt_mean_k",          0.0)
                    _obj.setdefault("bt_trend_k_per_min", 0.0)
                    _obj.setdefault("cloud_age_min",      0.0)
                    _obj.setdefault("anvil_extension_km", 0.0)
                    _obj.setdefault("overshooting_top",   0.0)
                    _obj.setdefault("ir_only_precursor",  0.0)

            curr_scaled_path = os.path.join("data", "radar", f"{timestamp}.png")
            _optflow_prev_path = select_optflow_prev_radar_path(
                _prev_radar_path,
                _last_valid_radar_path,
            )
            objects = assign_optical_flow_to_objects(
                objects,
                prev_radar_path=_optflow_prev_path,
                curr_radar_path=curr_scaled_path,
            )
            _last_valid_radar_path = remember_valid_radar_path(
                curr_scaled_path,
                _last_valid_radar_path,
            )
            _prev_radar_path = curr_scaled_path
            objects = assign_arome_to_objects(objects, timestamp)
            objects = assign_synoptic_features(objects, timestamp)
            objects = assign_extended_openmeteo(objects, timestamp)
            objects = assign_nowcast_to_objects(objects, timestamp)
            # ── Fix #2: Blitzdaten ZUERST holen, da assign_convective_indices
            # lightning_count_10km für hail_prob2 und lightning_jump benötigt ──
            lightning_data = []
            if timestamp:
                try:
                    from blitz_api import fetch_and_save_lightning
                    fetch_and_save_lightning(timestamp)
                except Exception as _le:
                    debug_log(f"[LIGHTNING] Fetch fehlgeschlagen: {_le}")
                lightning_file = os.path.join(SAVE_PATHS["lightning"], f"{timestamp}.json")
                if os.path.exists(lightning_file):
                    try:
                        with open(lightning_file, encoding="utf-8") as _f:
                            lightning_data = json.load(_f)
                    except Exception:
                        pass
            for obj in objects:
                # ── Size-Regresser: Größen-Features berechnen ─────────────────────
                try:
                    obj.setdefault("area_px", obj.get("area"))
                    obj.setdefault("radius_px", obj.get("size"))
                    if "bbox_px" not in obj and obj.get("contour"):
                        _xs = [float(_pt[0]) for _pt in obj["contour"] if len(_pt) >= 2]
                        _ys = [float(_pt[1]) for _pt in obj["contour"] if len(_pt) >= 2]
                        if _xs and _ys:
                            obj["bbox_px"] = [
                                min(_xs),
                                min(_ys),
                                max(_xs) - min(_xs),
                                max(_ys) - min(_ys),
                            ]
                    _sr = _size_reg_mod.get_size_regressor()
                    # B60: Geometrisches Label VOR LGBM-Prediction sichern.
                    # Verhindert Self-Distillation: record_size_label bekommt
                    # immer geometrisch gemessene Werte, nie LGBM-Vorhersagen.
                    _bbox_b60 = obj.get("bbox_px")
                    _bbox_wh_b60 = (
                        (_bbox_b60[2], _bbox_b60[3])
                        if _bbox_b60 and len(_bbox_b60) >= 4
                        else None
                    )
                    _geo_label = dict(obj)
                    _geo_label.update(
                        _size_reg_mod.geometric_size(
                            obj.get("area_px") or obj.get("area") or 0,
                            obj.get("radius_px") or obj.get("size") or 0,
                            _bbox_wh_b60,
                            _km_px_x,
                            _km_px_y,
                        )
                    )
                    _size_reg_mod.record_size_label(_geo_label, timestamp)
                    # Jetzt LGBM-Prediction auf obj anwenden
                    _size = _sr.predict(obj, timestamp, _km_px_x, _km_px_y)
                    obj.update(_size)
                    debug_log(
                        f"[SIZE-REG] id={obj.get('id')} "
                        f"area={obj.get('area_km2')} km² "
                        f"radius={obj.get('radius_km')} km "
                        f"src={obj.get('size_source')}"
                    )
                except Exception as _se:
                    debug_log(f"[SIZE-REG] Fehler bei Objekt {obj.get('id')}: {_se}")
                # ──────────────────────────────────────────────────────────────────
                if obj.get("lat") is not None and obj.get("lon") is not None:
                    obj["lightning_count_10km"] = _count_lightning_near(
                        float(obj["lat"]), float(obj["lon"]), lightning_data
                    )
            # NEU: alle konvektiven Indizes rein rechnerisch (kein Netzwerk).
            # Erwartet bereits gesetzte Felder: cape, t500_c, t700_c, cin, pw,
            # wind_speed_500hPa, wind_dir_500_*, arome_td2m, arome_ff10m,
            # arome_dd_*, arome_fl_height, core_ratio, lightning_count_10km.
            objects = assign_convective_indices(objects, timestamp)
            from compute_extra_features import assign_extra_features
            objects = assign_extra_features(objects)
            from datetime import datetime as _severity_datetime
            from severity_predict import assign_severity
            _severity_ts = _severity_datetime.strptime(timestamp, "%Y-%m-%d_%H-%M-%S") if timestamp else None
            objects = assign_severity(objects, weather_data, _severity_ts)
            _tawes_stations = fetch_tawes_stations()
            for _obj in objects:
                if _obj.get("lat") is not None and _obj.get("lon") is not None:
                    _measured_gust = max_gust_near(_obj["lat"], _obj["lon"], _tawes_stations, 30.0)
                    _obj["tawes_max_gust_kmh"] = _measured_gust
                    _obj["gust_warning"] = float(_obj.get("nowcast_ffx_kmh",0.0)) >= GUST_WARN_KMH or _measured_gust >= GUST_WARN_KMH
                    _obj["heavy_rain_warning"] = float(_obj.get("nowcast_rain_rate_1h",0.0)) >= HEAVY_RAIN_WARN_MM_PER_H
            # P-S01: Schwere-/Hagel-/Blitz-Maxima in tracking_memory akkumulieren
            # (severity_level etc. existieren erst nach assign_severity, daher hier).
            try:
                from track_statistics import accumulate_severity_maxima
                accumulate_severity_maxima(objects)
            except Exception as _e_sevacc:
                debug_log(f"[P-S01] accumulate_severity_maxima Fehler: {_e_sevacc}")

            # Hydro-Impact: nur oberliegendes Einzugsgebiet + Zeitversatz, keine Distanz-Attribution.
            try:
                _apply_hydro_productive_run(objects, timestamp)
            except Exception as _hydro_exc:
                debug_log(f"[HYDRO] Produktivlauf übersprungen: {_hydro_exc}")
            debug_log(f"Gefundene Objekte: {len(objects)}")
            # ── Strukturiertes Cell-Log (JSONL) ──────────────────────────
            _cell_log_path = os.path.join(
                SAVE_PATHS.get("evaluation", "train_data/evaluation"),
                "cells_log.jsonl"
            )
            os.makedirs(os.path.dirname(_cell_log_path), exist_ok=True)
            _cell_entry = {
                "ts":    timestamp,
                "count": len(objects),
                "cells": [
                    {
                        "id":         o.get("id"),
                        "lat":        o.get("lat"),
                        "lon":        o.get("lon"),
                        "size":       o.get("size"),
                        "core_ratio": round(float(o.get("core_ratio") or 0), 3),
                        "missing":    o.get("missing", 0),
                        "lineage":    o.get("lineage"),
                        "vx":         round(float(o.get("vx") or 0), 2),
                        "vy":         round(float(o.get("vy") or 0), 2),
                    }
                    for o in objects
                ],
            }
            try:
                with open(_cell_log_path, "a", encoding="utf-8") as _clf:
                    json.dump(_cell_entry, _clf, ensure_ascii=False)
                    _clf.write("\n")
            except Exception as _cl_exc:
                debug_log(f"[CELLS-LOG] Schreibfehler: {_cl_exc}")

            # Blitzdaten wurden bereits vor assign_convective_indices geholt (Fix #2)

        # P46: Risiko-Alarm für Orte mit E-Mail (max. 1× täglich, Risiko=3)
        if radar_ok and image is not None:
            try:
                _risk_alert_check(timestamp)
            except Exception as _rac_exc:
                debug_log(f"[RISK-ALERT] Fehler im Aufruf: {_rac_exc}")

        # P22/P28: No-cell-Frame — alle Downstream-States bereinigen damit
        # API/KMZ/Karte/Location-Warnungen nicht veraltet weiterleuchten.
        no_cells_handled = False
        if radar_ok and image is not None and not objects:
            # 1. Leeres Object-File (P22)
            _empty_obj_path = os.path.join(SAVE_PATHS["objects"], f"{timestamp}.json")
            _empty_weather_path = os.path.join(SAVE_PATHS["weather"], f"{timestamp}.json")
            try:
                with open(_empty_obj_path, "w", encoding="utf-8") as _eof:
                    json.dump([], _eof, ensure_ascii=False)
                debug_log(f"[NO-CELLS] Leeres Object-File gespeichert: {timestamp}")
            except Exception as _eoexc:
                debug_log(f"[NO-CELLS] Object-File Schreibfehler: {_eoexc}")

            # 2. Leere Location-Hits (P28) — löscht sichtbare Ort-Warnungen
            try:
                os.makedirs(SAVE_PATHS["evaluation"], exist_ok=True)
                _empty_loc_path = os.path.join(SAVE_PATHS["evaluation"], f"locations_{timestamp}.json")
                with open(_empty_loc_path, "w", encoding="utf-8") as _elf:
                    json.dump([], _elf, ensure_ascii=False)
                debug_log(f"[NO-CELLS] Leere Location-Hits gespeichert: {timestamp}")
            except Exception as _elexc:
                debug_log(f"[NO-CELLS] Location-File Schreibfehler: {_elexc}")

            # 3. Leeres KMZ (P28) — überschreibt altes forecast.kmz
            try:
                from config import FORECAST_ARROW_COLORS as _def_colors
                _runtime_horizons = runtime_config.get("ML_FORECAST_HORIZONS_MIN",
                                                        [10, 20, 30, 40, 60])
                _empty_forecasts = {h: [] for h in _runtime_horizons}
                save_forecast_as_kmz(
                    _empty_forecasts,
                    _def_colors,
                    current_objects=[],
                    location_hits=[],
                )
                debug_log(f"[NO-CELLS] Leeres KMZ gespeichert: {timestamp}")
            except Exception as _ekmz:
                debug_log(f"[NO-CELLS] KMZ Schreibfehler: {_ekmz}")

            # 4. Auto-Entwarnung für alle bisher betroffenen Orte (P28)
            if _prev_location_hit_names:
                debug_log(
                    f"[NO-CELLS] Auto-Entwarnung: {_prev_location_hit_names} "
                    f"— keine Zellen mehr sichtbar"
                )
                # _prev_location_hit_names wird in der nächsten Iteration
                # durch das Fehlen aktueller Hits automatisch gecleart.
            no_cells_handled = True
            try:
                _latest_objects = []
            except Exception:
                pass

        if radar_ok and image is not None and objects:
            if not weather_data:
                debug_log("[WARN] Keine Wetterdaten — Forecast läuft mit Defaults.")

            # ── P-S05: Zellalter + Klimatologie-Prior VOR ML-Forecast ─────────────
            # cell_age_min, clim_* sind ML_CELL_FEATURES → müssen vor dem Sequenz-
            # bau UND vor dem JSON-Save gesetzt sein (Train/Inference-Konsistenz).
            try:
                _clim_enrich(objects, timestamp)
            except Exception as _e_clim:
                debug_log(f"[P-S05] Klimatologie-Anreicherung übersprungen: {_e_clim}")

            # ── Finding #1 Fix: Windscherung + Hagel VOR ML-Forecast ──────────────
            # wind_shear_speed, hail_prob sind ML_CELL_FEATURES → müssen gesetzt
            # sein bevor predict_positions() den Feature-Vektor aufbaut.
            for _obj in objects:
                _shear_speed, _shear_cos, _shear_sin = _compute_wind_shear(_obj)
                _obj["wind_shear_speed"]   = _shear_speed
                _obj["wind_shear_dir_cos"] = _shear_cos
                _obj["wind_shear_dir_sin"] = _shear_sin

                if _obj.get("tracking_state") == "inactive_rain" or _obj.get("silent_tracking") is True:
                    _suppress_inactive_rain_warning_badges(_obj)
                    continue

                _hp, _hp_eff, _hw = _compute_hail_warning(_obj)
                _obj["hail_prob"]           = _hp
                _obj["hail_prob_effective"] = _hp_eff
                _obj["hail_warning"]        = _hw

                _sr = float(_obj.get("stationary_risk", 0.0))
                _obj["stationary_marker"] = bool(_sr >= STATIONARY_RISK_MARKER_THRESHOLD)

            # F1-FIX: predict_positions() VOR dem Speichern — schreibt forecast_lat_X
            # in-place in die Objekte, danach erst JSON-Dump damit /api/forecast Pfeile hat.
            forecasts_per_horizon = predict_positions(objects, timestamp, weather_data)

            # Radarbild speichern
            radar_file = os.path.join(SAVE_PATHS["radar"], f"{timestamp}.png")
            cv2.imwrite(radar_file, image)
            debug_log(f"Radarbild gespeichert als {radar_file}")

            # Fix #3: JSON-Save nach vollständiger Anreicherung — siehe weiter unten

            # Wetter speichern (falls vorhanden)
            object_file = os.path.join(SAVE_PATHS["objects"], f"{timestamp}.json")
            if weather_data:
                weather_file = os.path.join(SAVE_PATHS["weather"], f"{timestamp}.json")
                with open(weather_file, "w", encoding="utf-8") as _wf:
                    json.dump(
                        attach_schema_metadata(
                            weather_data,
                            source_object_file=object_file,
                            source_weather_file=weather_file,
                        ),
                        _wf,
                        ensure_ascii=False,
                    )
                debug_log(f"Wetterdaten gespeichert als {weather_file}")
            else:
                weather_file = os.path.join(SAVE_PATHS["weather"], f"{timestamp}.json")
            from config import ML_FORECAST_HORIZONS_MIN as _DEFAULT_HORIZONS
            from config import FORECAST_ARROW_COLORS as _DEFAULT_COLORS
            from config import FORECAST_ARROW_STYLE as _DEFAULT_STYLE
            horizons = runtime_config.get("ML_FORECAST_HORIZONS_MIN", _DEFAULT_HORIZONS)
            colors   = runtime_config.get("FORECAST_ARROW_COLORS",  _DEFAULT_COLORS)
            styles   = runtime_config.get("FORECAST_ARROW_STYLE",   _DEFAULT_STYLE)
            # Fix P08: KMZ enthält auch aktuelle Zellen und Location-Hits
            # (siehe kmz_export.save_forecast_as_kmz docstring).
            # location_hits werden weiter unten gesetzt, der erste Save liefert
            # nur Forecast+Zellen; nach annotate_locations folgt der finale Save.
            save_forecast_as_kmz(
                dict(zip(horizons, forecasts_per_horizon)),
                colors,
                current_objects=objects,
                location_hits=None,
                style_by_horizon=styles,
            )

            # wind_shear / hail_prob werden VOR predict_positions gesetzt
            # (Finding #1 Fix: ML-Modell bekommt vollständige Features)

            # Orte-Markierung bei Pfad-Durchquerung
            locations = runtime_config.get("LOCATIONS_WATCHLIST", [])
            from config import (
                MIN_MOVEMENT_FOR_ARROW_KMH as _MIN_ARROW_KMH,
                SLOW_CELL_MAX_KMH as _SLOW_MAX_KMH,
                SLOW_CELL_RADIUS_FACTOR as _SLOW_FACTOR,
            )
            _min_speed   = runtime_config.get("MIN_MOVEMENT_FOR_ARROW_KMH", _MIN_ARROW_KMH)
            _slow_max    = runtime_config.get("SLOW_CELL_MAX_KMH",          _SLOW_MAX_KMH)
            _slow_factor = runtime_config.get("SLOW_CELL_RADIUS_FACTOR",    _SLOW_FACTOR)
            # P-T09: Radarbild-Alter (min) auf ALLE Objekte schreiben, damit
            # annotate_locations stale-Forecasts erkennt — unabhängig vom ML-Status.
            try:
                from datetime import datetime as _dt_ra
                _radar_age_min = max(
                    0.0,
                    (_dt_ra.now() - _dt_ra.strptime(timestamp, "%Y-%m-%d_%H-%M-%S")).total_seconds() / 60.0,
                )
            except Exception:
                _radar_age_min = 0.0
            for _o in objects:
                _o["radar_age_min"] = round(_radar_age_min, 1)
            location_hits = annotate_locations(
                objects, locations, horizons, colors,
                min_speed_kmh=_min_speed,
                slow_cell_max_kmh=_slow_max,
                slow_radius_factor=_slow_factor,
            )
            os.makedirs(SAVE_PATHS["evaluation"], exist_ok=True)
            with open(os.path.join(SAVE_PATHS["evaluation"], f"locations_{timestamp}.json"), "w", encoding="utf-8") as f:
                json.dump(location_hits, f, indent=2, ensure_ascii=False)
            debug_log(f"Ort-Hits: {len(location_hits)} betroffene Orte")

            # Fix P08: finales KMZ inklusive Location-Hits neu schreiben.
            save_forecast_as_kmz(
                dict(zip(horizons, forecasts_per_horizon)),
                colors,
                current_objects=objects,
                location_hits=location_hits,
                style_by_horizon=styles,
                ir_tracks=_ir_tracks if '_ir_tracks' in dir() else [],
            )
            # ── Fix #3: Vollständig angereichertes JSON jetzt erst speichern ─────────
            # Enthält: forecast_lat_X, wind_shear_speed, hail_prob,
            #          hail_warning, stationary_marker, lightning_count_10km
            with open(object_file, "w", encoding="utf-8") as _of:
                json.dump(
                    attach_schema_metadata(
                        [{k: v for k, v in o.items() if k != "kf"} for o in objects],
                        source_object_file=object_file,
                        source_weather_file=weather_file,
                    ),
                    _of, ensure_ascii=False,
                )
            debug_log(f"Object-File gespeichert: {len(objects)} Objekte (vollständig angereichert)")
            _gust_cells  = [o["id"] for o in objects if o.get("gust_warning")]
            _rain_cells  = [o["id"] for o in objects if o.get("heavy_rain_warning")]
            _hail_cells  = [o["id"] for o in objects if o.get("hail_warning")]
            if _gust_cells: debug_log(f"[WARN] Böen >= {GUST_WARN_KMH} km/h: {_gust_cells}")
            if _rain_cells: debug_log(f"[WARN] Starkregen >= {HEAVY_RAIN_WARN_MM_PER_H} mm/h: {_rain_cells}")
            if _hail_cells: debug_log(f"[WARN] Hagelwarnung: {_hail_cells}")

            # ── Auto-Entwarnung (F47) ─────────────────────────────────────────
            _current_hit_names = {h["name"] for h in location_hits}
            _new_hit_names = _current_hit_names - _prev_location_hit_names
            _cleared       = _prev_location_hit_names - _current_hit_names

            # ── Hilfsfunktion: Frühester Forecast-Horizont eines Orts-Treffers ──
            def _earliest_forecast_horizon(loc_hit: dict) -> int:
                """
                Gibt den kleinsten Horizont-Key > 0 zurück der einen Treffer hat.
                Key 0 (current) wird ignoriert — der wird immer gewarnt.
                Gibt 9999 zurück wenn keine Forecast-Horizonte getroffen wurden.
                """
                forecast_keys = []
                for k in loc_hit.get("hits", {}).keys():
                    try:
                        horizon = int(k)
                    except (TypeError, ValueError):
                        continue
                    if horizon > 0:
                        forecast_keys.append(horizon)
                return min(forecast_keys) if forecast_keys else 9999

            def _has_current_horizon(loc_hit: dict) -> bool:
                """True wenn Horizon-Key 0 als int oder String vorhanden ist."""
                for k in loc_hit.get("hits", {}).keys():
                    try:
                        if int(k) == 0:
                            return True
                    except (TypeError, ValueError):
                        continue
                return False

            def _earliest_cell_id(loc_hit: dict):
                """B98: cell_id des frühesten Treffers (Horizon 0 > kleinster positiver Horizon)."""
                hits = loc_hit.get("hits") or {}
                if not hits:
                    return None
                try:
                    _, h_info = min(hits.items(), key=lambda kv: int(kv[0]))
                    return h_info.get("cell_id") or None
                except Exception:
                    return None

            def _hit_is_kinematic(loc_hit: dict) -> bool:
                """
                Gibt True zurück wenn mindestens eine treffende Zelle
                kinematische (unsichere) Vorhersage hat UND kein Current-Treffer vorliegt.

                Current-Treffer (Horizont-Key 0) bedeuten: Zelle ist JETZT im Ortsradius.
                Diese werden immer sofort gewarnt — unabhängig vom forecast_mode der Zelle.
                Die 2-Frame-Bestätigung gilt ausschließlich für reine Forecast-Treffer
                (Horizont > 0) mit unsicherem kinematischem Forecast.
                """
                # Current-Hit vorhanden (Horizont-Key 0) → nie verzögern
                if _has_current_horizon(loc_hit):
                    return False
                # P-T09: Stale-Forecast (Radarbild älter als Horizont) → wie current
                # behandeln, nicht verzögern. Die Eingabedaten sind bereits alt; ein
                # weiterer Frame würde sie nur älter machen.
                for _h_info in loc_hit.get("hits", {}).values():
                    if _h_info.get("stale"):
                        return False
                hit_cell_ids = {
                    h.get("cell_id")
                    for h in loc_hit.get("hits", {}).values()
                    if h.get("cell_id")
                }
                for _obj in objects:
                    if _obj.get("id") in hit_cell_ids:
                        if _obj.get("forecast_mode") == "kinematic":
                            return True
                return False

            # ── Pending zurücksetzen für Orte die nicht mehr getroffen werden
            for _pname in list(_location_warn_pending.keys()):
                if _pname not in _current_hit_names:
                    debug_log(
                        f"[EMAIL] {_pname}: Treffer weg in Frame "
                        f"{_location_warn_pending[_pname]} — pending zurückgesetzt"
                    )
                    del _location_warn_pending[_pname]

            # ── E-Mail: Neue Orts-Treffer (inkl. 2-Frame-Logik) ──────────
            _loc_email_map = {
                loc.get("name", ""): loc.get("email", "")
                for loc in locations
                if loc.get("email", "").strip()
            }
            # WhatsApp-Empfaenger-Map — gleiches Konzept wie _loc_email_map
            _loc_wa_map = {
                loc.get("name", ""): loc.get("whatsapp", "")
                for loc in locations
                if loc.get("whatsapp", "").strip()
            }
            _ready_to_warn = set()

            for _loc_hit in location_hits:
                _lname = _loc_hit["name"]
                _emails = _loc_email_map.get(_lname, "")
                if not _emails:
                    continue
                # B98: Einmal-pro-Zelle — gleiche cell_id nicht doppelt warnen.
                _hit_cell_id = _earliest_cell_id(_loc_hit)
                if _hit_cell_id and _hit_cell_id in _warned_cells.get(_lname, set()):
                    continue
                # Fallback: keine cell_id ermittelbar → altes Verhalten
                if not _hit_cell_id and _lname in _location_warned:
                    continue

                if _hit_cell_id and _lname in _location_warned:
                    from config import WARN_MAX_HORIZON_MIN as _WARN_CELL_DEF
                    _warn_cell_max_h = int(runtime_config.get("WARN_MAX_HORIZON_MIN", _WARN_CELL_DEF))
                    _earliest_cell_h = _earliest_forecast_horizon(_loc_hit)
                    if _has_current_horizon(_loc_hit) or _earliest_cell_h <= _warn_cell_max_h:
                        _ready_to_warn.add(_lname)
                    else:
                        debug_log(
                            f"[EMAIL] {_lname}: neue Zelle {_hit_cell_id}, aber frühester Horizont "
                            f"+{_earliest_cell_h} min > Vorwarnzeit {_warn_cell_max_h} min — kein Alarm"
                        )

                if _lname in _new_hit_names:
                    # Neuer Treffer in diesem Frame
                    if _hit_is_kinematic(_loc_hit):
                        # Kinematisch → 2 Frames warten
                        _location_warn_pending[_lname] = 1
                        debug_log(
                            f"[EMAIL] {_lname}: kinematische Vorhersage — "
                            f"warte auf Frame 2 zur Bestätigung"
                        )
                    else:
                        # ML-Vorhersage → sofort warnen (wenn Vorwarnzeit-Schwelle erfüllt)
                        from config import WARN_MAX_HORIZON_MIN as _WARN_DEF
                        _warn_max_h = int(runtime_config.get("WARN_MAX_HORIZON_MIN", _WARN_DEF))
                        _earliest_h = _earliest_forecast_horizon(_loc_hit)
                        # Horizon 0 (current) oder frühester Forecast ≤ Schwelle → warnen
                        _has_current = _has_current_horizon(_loc_hit)
                        if _has_current or _earliest_h <= _warn_max_h:
                            _ready_to_warn.add(_lname)
                        else:
                            debug_log(
                                f"[EMAIL] {_lname}: frühester Horizont +{_earliest_h} min "
                                f"> Vorwarnzeit {_warn_max_h} min — kein Alarm"
                            )
                elif _lname in _location_warn_pending:
                    # Fortsetzung: Ort war schon im letzten Frame getroffen
                    _location_warn_pending[_lname] += 1
                    if _location_warn_pending[_lname] >= 2:
                        debug_log(
                            f"[EMAIL] {_lname}: 2 aufeinanderfolgende Frames bestätigt "
                            f"— Warnung wird gesendet"
                        )
                        from config import WARN_MAX_HORIZON_MIN as _WARN_DEF2
                        _warn_max_h2 = int(runtime_config.get("WARN_MAX_HORIZON_MIN", _WARN_DEF2))
                        _earliest_h2 = _earliest_forecast_horizon(_loc_hit)
                        _has_current2 = _has_current_horizon(_loc_hit)
                        if _has_current2 or _earliest_h2 <= _warn_max_h2:
                            _ready_to_warn.add(_lname)
                        else:
                            debug_log(
                                f"[EMAIL] {_lname}: frühester Horizont +{_earliest_h2} min "
                                f"> Vorwarnzeit {_warn_max_h2} min — kein Alarm (nach 2-Frame-Prüfung)"
                            )
                        del _location_warn_pending[_lname]

            if _ready_to_warn:
                try:
                    from email_notifier import send_warning_email
                    for _loc_hit in location_hits:
                        if _loc_hit["name"] not in _ready_to_warn:
                            continue
                        _emails = _loc_email_map.get(_loc_hit["name"], "")
                        if _emails:
                            if send_warning_email(
                                _loc_hit["name"],
                                _loc_hit["hits"],
                                _emails,
                                timestamp,
                            ):
                                _location_warned.add(_loc_hit["name"])
                                # B98: Zelle merken — selbe Zelle löst keinen weiteren Alarm aus
                                _cid = _earliest_cell_id(_loc_hit)
                                if _cid:
                                    _warned_cells.setdefault(_loc_hit["name"], set()).add(_cid)
                                debug_log(f"[EMAIL] Warnung gesendet: {_loc_hit['name']}")
                except Exception as _e:
                    debug_log(f"[EMAIL] Warnung fehlgeschlagen: {_e}")

            # ── WhatsApp: Neue Orts-Treffer (best-effort, kein State) ────
            if _ready_to_warn:
                try:
                    from whatsapp_notifier import send_warning_wa
                    for _loc_hit in location_hits:
                        if _loc_hit["name"] not in _ready_to_warn:
                            continue
                        _wa = _loc_wa_map.get(_loc_hit["name"], "")
                        if _wa:
                            _wa_ok = send_warning_wa(
                                _loc_hit["name"],
                                _loc_hit["hits"],
                                _wa,
                                timestamp,
                            )
                            if _wa_ok:
                                debug_log(f"[WA] Warnung gesendet: {_loc_hit['name']}")
                            else:
                                debug_log(
                                    f"[WA] Warnung NICHT gesendet: {_loc_hit['name']} "
                                    f"(Cooldown oder Empfaenger-Fehler — Details oben)"
                                )
                        else:
                            debug_log(
                                f"[WA] Kein WhatsApp-Eintrag fuer {_loc_hit['name']} "
                                f"— Feld leer oder nicht konfiguriert."
                            )
                except Exception as _e:
                    debug_log(f"[WA] Warnung fehlgeschlagen: {_e}")

            # ── E-Mail: Entwarnung (nur wenn vorher gewarnt wurde) ────────
            if _cleared:
                try:
                    from email_notifier import send_allclear_email
                    for _loc_name in sorted(_cleared):
                        if _loc_name not in _location_warned:
                            # Kein Alarm gesendet → keine Entwarnung nötig
                            continue
                        _emails = _loc_email_map.get(_loc_name, "")
                        if _emails:
                            ok = send_allclear_email(_loc_name, _emails)
                            if ok:
                                _location_warned.discard(_loc_name)
                                _warned_cells.pop(_loc_name, None)  # B98: neue Zellen können wieder warnen
                                debug_log(f"[EMAIL] Entwarnung gesendet: {_loc_name}")
                            else:
                                debug_log(
                                    f"[EMAIL] Entwarnung fehlgeschlagen — "
                                    f"Warnstatus bleibt aktiv: {_loc_name}"
                                )
                except Exception as _e:
                    debug_log(f"[EMAIL] Entwarnung fehlgeschlagen: {_e}")

            # ── WhatsApp: Entwarnung bewusst NICHT implementiert ─────────
            # Design-Entscheidung (B108): WhatsApp sendet ausschließlich Warnungen.
            # Entwarnungen erfolgen nur per E-Mail.

            _prev_location_hit_names = _current_hit_names

        elif not no_cells_handled:
            debug_log("Keine vollständigen Daten → Keine Speicherung")

        create_movement_gif("movement.gif")
        create_visualized_radar()

        # Uploads
        upload_file_ftp("data/overlay.png", "overlay.png")
        upload_file_ftp("forecast.kmz", "forecast.kmz")
        upload_file_ftp("movement.gif", "movement.gif")

        try:
            latest_object = sorted(os.listdir(SAVE_PATHS["objects"]))[-1]
            upload_file_ftp(os.path.join(SAVE_PATHS["objects"], latest_object), "latest_objects.json")
        except Exception:
            debug_log("Kein Object-File vorhanden — überspringe Upload von latest_objects.json")

        # Adaptiver Intervall — 3 Stufen:
        #   aktive Zellen (missing==0)          → 120s  (2 min)
        #   0–120 min nach letzter Zelle        → 300s  (5 min, Nachbeobachtung)
        #   ≥ 120 min ohne Zellen / nie         → 900s  (15 min, Ruhe)
        _cells_now = bool(objects and any(o.get("missing", 0) == 0 for o in objects))
        if _cells_now:
            _last_cells_active_ts = time.time()
        # Risk-Watch: kurzer Intervall auch bei Gewitterpotenzial / CB-IR-Vorläuferzelle.
        # IR-Tracks dieses Zyklus werden mitgegeben (kein zusätzlicher HTTP-Call bei
        # IR-Treffer). _last_cells_active_ts bleibt unberührt (Nachbeobachtung bleibt an
        # echte Radar-Zellen gebunden).
        _risk_watch = risk_watch_active(_ir_tracks if '_ir_tracks' in dir() else [])
        from config import NO_CELLS_SLOW_INTERVAL_TIMEOUT_S as _NCST_CFG
        _timeout_s = float(runtime_config.get("NO_CELLS_SLOW_INTERVAL_TIMEOUT_S", _NCST_CFG))
        _elapsed_since_cells = (
            (time.time() - _last_cells_active_ts)
            if _last_cells_active_ts is not None else float("inf")
        )
        _within_timeout = _elapsed_since_cells < _timeout_s
        if _cells_now:
            _sleep = runtime_config.get("LOOP_INTERVAL_CELLS_S", LOOP_INTERVAL_CELLS_S)
            debug_log(f"[LOOP] Zellen aktiv → kurzer Intervall ({_sleep}s)")
        elif _risk_watch:
            _sleep = runtime_config.get("LOOP_INTERVAL_CELLS_S", LOOP_INTERVAL_CELLS_S)
            debug_log(
                f"[LOOP] Risk-Watch (Gewitterpotenzial/CB-IR-Vorläufer) "
                f"→ kurzer Intervall ({_sleep}s)"
            )
        elif _within_timeout:
            _sleep = runtime_config.get(
                "LOOP_INTERVAL_NACHBEOBACHTUNG_S", LOOP_INTERVAL_NACHBEOBACHTUNG_S
            )
            debug_log(
                f"[LOOP] Nachbeobachtung {int(_elapsed_since_cells // 60)} / "
                f"{int(_timeout_s // 60)} min → mittlerer Intervall ({_sleep}s)"
            )
        else:
            _sleep = runtime_config.get("LOOP_INTERVAL_NO_CELLS_S", LOOP_INTERVAL_NO_CELLS_S)
            debug_log(
                f"[LOOP] Ruhe > {int(_timeout_s // 60)} min → langer Intervall ({_sleep}s)"
            )
        time.sleep(_sleep)

if __name__ == "__main__":
    import watchdog_heartbeat as _wdh
    _wdh.start()                        # systemd READY=1 + Watchdog-Ping alle 25 s
    main_loop()
