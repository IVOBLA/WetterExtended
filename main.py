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
from fetch_arome_openmeteo import assign_arome_to_objects
from fetch_synoptic_features import assign_synoptic_features
from orographic_module import assign_orographic_scores
from fetch_openmeteo_extended import assign_extended_openmeteo
from fetch_geosphere_nowcast import assign_nowcast_to_objects
from compute_convective_indices import assign_convective_indices
from fetch_tawes_gust import fetch_tawes_stations, max_gust_near
from ir_cell_detection import detect_ir_cells
from ir_cell_tracking import update_ir_tracking
import math as _math_main
import runtime_config
from locations_check import annotate_locations
from config import (HAIL_WARN_THRESHOLD, STATIONARY_RISK_MARKER_THRESHOLD,
                    GUST_WARN_KMH, HEAVY_RAIN_WARN_MM_PER_H)

_ROI_CACHE = None
_RISK_ALERT_LOG = os.path.join(
    SAVE_PATHS.get("evaluation", "train_data/evaluation"),
    "risk_alert_sent.json"
)


def _risk_alert_check(timestamp: str) -> None:
    import json as _j
    from datetime import datetime as _dt, timezone as _tz
    _today = _dt.now(_tz.utc).strftime("%Y-%m-%d")
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
    try:
        import requests as _req
        _resp = _req.get("http://127.0.0.1:5000/api/risk_grid", timeout=5)
        if _resp.status_code != 200:
            return
        _grid = _resp.json().get("cells", [])
    except Exception as _exc:
        debug_log(f"[RISK-ALERT] Risk-Grid nicht erreichbar: {_exc}")
        return
    _changed = False
    for loc in _locs_with_email:
        loc_name = loc.get("name", "?")
        loc_lat = float(loc.get("lat", 0))
        loc_lon = float(loc.get("lon", 0))
        email = loc.get("email", "").strip()
        if _sent.get(loc_name) == _today:
            continue
        best_cell = min(_grid, key=lambda c: abs(c["lat"] - loc_lat) + abs(c["lon"] - loc_lon), default=None)
        if not best_cell or best_cell.get("risk", 0) < 3:
            continue
        info = best_cell.get("info", {})
        try:
            from email_notifier import send_risk_alert_email
            ok = send_risk_alert_email(location_name=loc_name, dominant=info.get("dominant", "atm"), details=info, recipient=email)
            if ok:
                _sent[loc_name] = _today
                _changed = True
                debug_log(f"[RISK-ALERT] ✅ Alarm gesendet: {loc_name} → {email}")
            else:
                debug_log(f"[RISK-ALERT] ❌ E-Mail fehlgeschlagen: {loc_name}")
        except Exception as _exc:
            debug_log(f"[RISK-ALERT] Fehler: {_exc}")
    if _changed:
        try:
            os.makedirs(os.path.dirname(_RISK_ALERT_LOG), exist_ok=True)
            with open(_RISK_ALERT_LOG, "w", encoding="utf-8") as _f:
                _j.dump(_sent, _f, indent=2, ensure_ascii=False)
        except Exception as _se:
            debug_log(f"[RISK-ALERT] Cooldown speichern fehlgeschlagen: {_se}")

def _count_lightning_near(lat: float, lon: float,
                          lightning_data: list, radius_km: float = 10.0) -> int:
    """Zählt Blitze im radius_km-Umkreis. Nutzt einfache Grad-Näherung."""
    if not lightning_data:
        return 0
    count = 0
    lat_deg = radius_km / 111.0
    lon_deg = radius_km / (111.0 * abs(_math_main.cos(_math_main.radians(lat))) + 1e-9)
    for bolt in lightning_data:
        blat = bolt.get("lat") or bolt.get("y")
        blon = bolt.get("lon") or bolt.get("x")
        if blat is None or blon is None:
            continue
        if abs(float(blat) - lat) <= lat_deg and abs(float(blon) - lon) <= lon_deg:
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


def main_loop():
    image_path = "data/latest.png"

    _prev_radar_path = None
    _prev_location_hit_names: set = set()  # F47: Auto-Entwarnung
    _last_cells_active_ts: float | None = None  # Zeitpunkt der letzten aktiven Zelle
    # 2-Frame-Bestätigung für unsichere Vorhersagen (kinematic forecast_mode):
    # Orte die schon 1× getroffen wurden aber noch auf Frame 2 warten.
    _location_warn_pending: dict = {}   # {loc_name: frame_count}
    # Orte für die in diesem Session bereits eine Warnung gesendet wurde
    # (Entwarnung nur senden wenn vorher eine Warnung gesandt wurde).
    _location_warned: set = set()

    while True:
        runtime_config.reload_overrides()
        global _ROI_CACHE
        _bbox = runtime_config.get("BBOX_KAERNTEN_EXTENDED", BBOX_KAERNTEN_EXTENDED)
        _ROI_CACHE = get_roi_from_bbox(_bbox)
        debug_log("Neuer Zyklus gestartet...")
        radar_ok = download_kmz()

        if not radar_ok:
            debug_log("[SKIP] Radarbild ungültig oder nicht neu → nächster Zyklus.")
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
            if _elapsed_skip < _nb_s_skip:
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
                _ir_cells_raw = detect_ir_cells(timestamp=timestamp)
                _ir_tracks = update_ir_tracking(_ir_cells_raw, timestamp)

                # IR↔Radar Lineage-Matching:
                # Maximaler Abstand für ein IR↔Radar-Match: 40 km
                _IR_MATCH_KM = 40.0
                _matched_ir_ids = set()
                for _obj in objects:
                    _obj_lat = _obj.get("lat", 0.0)
                    _obj_lon = _obj.get("lon", 0.0)
                    _best_dist = float("inf")
                    _best_ir = None
                    for _ir in _ir_tracks:
                        from math import radians as _rad, cos as _cos, sin as _sin, sqrt as _sq, atan2 as _at2
                        _dlat = _rad(_ir["lat"] - _obj_lat)
                        _dlon = _rad(_ir["lon"] - _obj_lon)
                        _a = _sin(_dlat/2)**2 + _cos(_rad(_obj_lat)) * _cos(_rad(_ir["lat"])) * _sin(_dlon/2)**2
                        _d = 6371.0 * 2 * _at2(_sq(_a), _sq(1-_a))
                        if _d < _best_dist:
                            _best_dist = _d
                            _best_ir = _ir
                    if _best_ir is not None and _best_dist <= _IR_MATCH_KM:
                        _obj["ir_match_id"]           = _best_ir.get("ir_id")
                        _obj["bt_min_k"]              = _best_ir.get("bt_min_k", 0.0)
                        _obj["bt_mean_k"]             = _best_ir.get("bt_mean_k", 0.0)
                        _obj["bt_trend_k_per_min"]    = _best_ir.get("bt_trend_k_per_min", 0.0)
                        _obj["cloud_age_min"]         = _best_ir.get("cloud_age_min", 0.0)
                        _obj["anvil_extension_km"]    = _best_ir.get("anvil_extension_km", 0.0)
                        _obj["overshooting_top"]      = _best_ir.get("overshooting_top", 0.0)
                        _obj["ir_only_precursor"]     = 0.0
                        _matched_ir_ids.add(_best_ir.get("ir_id"))
                        if isinstance(_best_ir.get("radar_match_ids"), list):
                            if _obj.get("id") not in _best_ir["radar_match_ids"]:
                                _best_ir["radar_match_ids"].append(_obj.get("id"))
                    else:
                        _obj.setdefault("ir_match_id",        None)
                        _obj.setdefault("bt_min_k",           0.0)
                        _obj.setdefault("bt_mean_k",          0.0)
                        _obj.setdefault("bt_trend_k_per_min", 0.0)
                        _obj.setdefault("cloud_age_min",      0.0)
                        _obj.setdefault("anvil_extension_km", 0.0)
                        _obj.setdefault("overshooting_top",   0.0)
                        _obj.setdefault("ir_only_precursor",  0.0)

                # IR-Cells OHNE Radar-Match: ir_only_precursor = 1.0
                for _ir in _ir_tracks:
                    if _ir.get("ir_id") not in _matched_ir_ids:
                        _ir["ir_only_precursor"] = 1.0

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

            curr_scaled_path = os.path.join("data", "radar", f"radar_{timestamp}.png")
            objects = assign_optical_flow_to_objects(
                objects,
                prev_radar_path=_prev_radar_path,
                curr_radar_path=curr_scaled_path,
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
        if radar_ok and image is not None and not objects:
            # 1. Leeres Object-File (P22)
            _empty_obj_path = os.path.join(SAVE_PATHS["objects"], f"{timestamp}.json")
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

        if radar_ok and image is not None and objects:
            if not weather_data:
                debug_log("[WARN] Keine Wetterdaten — Forecast läuft mit Defaults.")

            # ── Finding #1 Fix: Windscherung + Hagel VOR ML-Forecast ──────────────
            # wind_shear_speed, hail_prob sind ML_CELL_FEATURES → müssen gesetzt
            # sein bevor predict_positions() den Feature-Vektor aufbaut.
            for _obj in objects:
                _shear_speed, _shear_cos, _shear_sin = _compute_wind_shear(_obj)
                _obj["wind_shear_speed"]   = _shear_speed
                _obj["wind_shear_dir_cos"] = _shear_cos
                _obj["wind_shear_dir_sin"] = _shear_sin

                _hp = _compute_hail_prob(_obj)
                _obj["hail_prob"]    = _hp
                _obj["hail_warning"] = bool(_hp >= HAIL_WARN_THRESHOLD)

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
            if weather_data:
                weather_file = os.path.join(SAVE_PATHS["weather"], f"{timestamp}.json")
                with open(weather_file, "w", encoding="utf-8") as _wf:
                    json.dump(weather_data, _wf, ensure_ascii=False)
                debug_log(f"Wetterdaten gespeichert als {weather_file}")
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
            object_file = os.path.join(SAVE_PATHS["objects"], f"{timestamp}.json")
            with open(object_file, "w", encoding="utf-8") as _of:
                json.dump(
                    [{k: v for k, v in o.items() if k != "kf"} for o in objects],
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

            # ── Hilfsfunktion: Ist die Vorhersage für diesen Orts-Treffer unsicher?
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
                if 0 in loc_hit.get("hits", {}):
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
            _ready_to_warn = set()

            for _loc_hit in location_hits:
                _lname = _loc_hit["name"]
                _emails = _loc_email_map.get(_lname, "")
                if not _emails or _lname in _location_warned:
                    continue

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
                        # ML-Vorhersage → sofort warnen
                        _ready_to_warn.add(_lname)
                elif _lname in _location_warn_pending:
                    # Fortsetzung: Ort war schon im letzten Frame getroffen
                    _location_warn_pending[_lname] += 1
                    if _location_warn_pending[_lname] >= 2:
                        debug_log(
                            f"[EMAIL] {_lname}: 2 aufeinanderfolgende Frames bestätigt "
                            f"— Warnung wird gesendet"
                        )
                        _ready_to_warn.add(_lname)
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
                                debug_log(f"[EMAIL] Warnung gesendet: {_loc_hit['name']}")
                except Exception as _e:
                    debug_log(f"[EMAIL] Warnung fehlgeschlagen: {_e}")

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
                            send_allclear_email(_loc_name, _emails)
                            _location_warned.discard(_loc_name)
                            debug_log(f"[EMAIL] Entwarnung gesendet: {_loc_name}")
                except Exception as _e:
                    debug_log(f"[EMAIL] Entwarnung fehlgeschlagen: {_e}")

            _prev_location_hit_names = _current_hit_names

        else:
            debug_log("Keine vollständigen Daten → Keine Speicherung")
            save_forecast_as_kmz({}, {})

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
