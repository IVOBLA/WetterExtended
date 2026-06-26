# ir_cell_tracking.py
"""
Phase E — Task E2: IR-Cell Kalman-Tracking.

Trackt IR-Cells zwischen aufeinanderfolgenden ir_cells_*.json Frames.
Eigener ID-Raum: ir_0, ir_1, … — kein Konflikt mit Radar-Zell-IDs.

Jede verfolgte IR-Cell erhält zusätzlich:
  - vx_px_min / vy_px_min  : Geschwindigkeit in Grad/min (vereinfacht)
  - bt_trend_k_per_min     : BT-Änderungsrate [K/min]
  - cloud_age_min          : Alter des Tracklets [min]
  - anvil_extension_km     : Abstand Schwerpunkt → kältestes Pixel × Richtung [km]
  - ir_only_precursor      : 1.0 wenn kein Radar-Match (wird in E3 gesetzt)
  - radar_match_ids        : [] (wird in E3 befüllt)

Persistenz:
  - Tracking-State wird in train_data/ir_cells/ir_track_state.json gespeichert.
  - Beim nächsten Aufruf wird der State geladen und fortgesetzt.
"""

import json
import os
from datetime import datetime
from glob import glob
from math import radians, cos, sin, sqrt, atan2

from config import SAVE_PATHS, IR_TRACK_MAX_MISSING, IR_WATCH_MIN_SCORE, IR_PRE_CB_MIN_SCORE, IR_CB_MIN_SCORE, IR_WATCH_MAX_PUBLIC_AGE_MIN, IR_PUBLIC_WATCH_VISIBLE, CLOUD_HEIGHT_ALERT_THRESHOLD_M

# B252: Maximale Anzahl aufeinanderfolgender Zyklen mit unveränderten
# tiff_file + observation_timestamp, bevor missing inkrementiert wird.
_IR_MAX_STALE_OBS_CYCLES_DEFAULT = 2

try:
    import runtime_config
except Exception:
    runtime_config = None

try:
    from cell_lineage import ensure_ir_track_cell_id, ensure_ir_tracks_cell_ids
except Exception:
    ensure_ir_track_cell_id = None
    ensure_ir_tracks_cell_ids = None

def debug_log(*args, **kwargs):
    pass

_SAVE_DIR   = SAVE_PATHS.get("ir_cells", "train_data/ir_cells/")
_STATE_FILE = os.path.join(_SAVE_DIR, "ir_track_state.json")

# Maximaler Abstand [Grad] zweier IR-Cells zwischen Frames für ein Match.
# MSG 15 min × max. 120 km/h Verlagerung ÷ 111 km/Grad ≈ 0.27°
_MAX_MATCH_DEG = 0.30




def _cfg(name, default):
    if runtime_config is not None:
        try:
            return runtime_config.get(name, default)
        except Exception:
            return default
    return default


def _public_label(stage: str) -> str:
    return {
        "ir_watch_candidate": "IR-Frühphase",
        "ir_pre_cb": "IR-Vorläufer",
        "ir_cb_precursor": "CB-IR-Vorläufer",
        "radar_confirmed": "Radar bestätigt",
    }.get(stage or "", "IR-Frühphase")


def _age_min(ts: str | None) -> float:
    dt = _ts_to_dt(ts) if ts else None
    if not dt:
        return 0.0
    return max(0.0, (datetime.utcnow() - dt).total_seconds() / 60.0)


def _forecast_fields(track: dict) -> dict:
    """Berechnet Prognose-Felder für einen IR-Track.

    Priorität:
    1. ir_track  – vx/vy aus Kalman-Bewegungsableitung (≥2 Frames)
    2. steering_wind – 700-hPa-Steuerwind aus track (1 Frame)
    3. none – kein Fallback verfügbar
    """
    vx = float(track.get("vx_deg_min", 0.0) or 0.0)
    vy = float(track.get("vy_deg_min", 0.0) or 0.0)

    if abs(vx) + abs(vy) > 0:
        mode = "ir_track"
        conf = 0.55
    else:
        # B254: Steuerwind-Fallback wenn 700-hPa-Wind im Track vorhanden
        _spd = float(track.get("wind_speed_700hPa", 0.0) or 0.0)
        _cos = float(track.get("wind_dir_cos", 0.0) or 0.0)
        _sin = float(track.get("wind_dir_sin", 0.0) or 0.0)
        if _spd > 0.1 and (abs(_cos) + abs(_sin)) > 0.01:
            # Empirikregel: ~70 % der 700-hPa-Windgeschwindigkeit
            # Wind-Richtung: meteorologisch (woher kommt der Wind)
            # Zell-Bewegung: in Windrichtung
            # _cos/sin sind Komponenten des Einheitsvektors der Zugrichtung
            # (aus fetch_700hpa_wind_per_object_slim.py, bereits als cos/sin)
            _cell_speed_kmh = _spd * 0.70          # km/h
            _cell_speed_deg_min = _cell_speed_kmh / (111.0 * 60.0)  # Grad/min
            vx = _cell_speed_deg_min * _sin        # ost-west (cos/sin-Konvention)
            vy = _cell_speed_deg_min * _cos        # nord-süd
            mode = "steering_wind"
            conf = 0.35
        else:
            mode = "none"
            conf = 0.2

    lat = float(track.get("lat", 0.0) or 0.0)
    lon = float(track.get("lon", 0.0) or 0.0)
    out = {"forecast_mode": mode, "forecast_confidence": conf}
    for m in (10, 20, 30, 40, 60):
        out[f"forecast_lat_{m}"] = round(lat + vy * m, 5)
        out[f"forecast_lon_{m}"] = round(lon + vx * m, 5)
    return out

def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1-a))


def _deg_dist(lat1, lon1, lat2, lon2) -> float:
    """Grobe Gradabstand-Näherung (kein Haversine — nur für Matching)."""
    return ((lat2 - lat1)**2 + (lon2 - lon1)**2) ** 0.5



def _is_truthy_precursor(value) -> bool:
    try:
        return float(value) == 1.0
    except (TypeError, ValueError):
        return bool(value)


def _lineage_enabled() -> bool:
    if runtime_config is not None:
        try:
            return bool(runtime_config.get("IR_LINEAGE_ENABLED", True))
        except Exception:
            pass
    return True


def _normalize_ir_track(track: dict, *, default_timestamp: str | None = None) -> dict:
    """Ergänzt und harmonisiert die 1C-Semantikfelder eines IR-Tracks."""
    if not isinstance(track, dict):
        return track

    ts = track.get("last_timestamp") or track.get("timestamp") or default_timestamp
    radar_confirmed = bool(track.get("radar_confirmed") or track.get("radar_matched"))
    if not radar_confirmed and "ir_only_precursor" in track:
        radar_confirmed = not _is_truthy_precursor(track.get("ir_only_precursor"))

    track["_type"] = "ir_precursor_cell"
    if track.get("ir_id") and not track.get("ir_track_id"):
        track["ir_track_id"] = track.get("ir_id")
    track.setdefault("source_type", "ir108")
    track.setdefault("radar_track_id", None)
    track.setdefault("radar_match_ids", [])
    if not isinstance(track.get("radar_match_ids"), list):
        track["radar_match_ids"] = []
    track.setdefault("first_seen_source", "ir108")
    obs_ts = track.get("last_seen_observation_timestamp") or track.get("observation_timestamp") or track.get("source_timestamp") or ts
    track.setdefault("first_seen_observation_timestamp", track.get("first_seen_timestamp") or obs_ts)
    track.setdefault("last_seen_observation_timestamp", obs_ts)
    track.setdefault("observation_timestamp", obs_ts)
    track.setdefault("first_seen_timestamp", track.get("first_seen_observation_timestamp") or obs_ts)
    track.setdefault("source_timestamp", obs_ts)
    if ts and not track.get("source_timestamp"):
        track["source_timestamp"] = ts
    track.setdefault("cb_candidate", True)
    track.setdefault("cb_only_reason", "ir108_cold_top_and_met_filter")
    track.setdefault("area_growth_px_per_min", 0.0)
    track.setdefault("area_growth_km2_per_min", 0.0)
    track.setdefault("cloud_height_trend_m_per_min", 0.0)
    track.setdefault("motion_quality", "unknown")

    if radar_confirmed:
        track["ir_stage"] = "radar_confirmed"
        track["status"] = "radar_confirmed"
        track["radar_confirmed"] = True
        track["is_potential_new_cell"] = False
        track["display_as_precursor"] = False
        track["ir_only_precursor"] = 0.0
    else:
        stage = track.get("ir_stage") or track.get("status") or "ir_watch_candidate"
        if stage == "ir_precursor":
            stage = "ir_cb_precursor"
        track["ir_stage"] = stage
        track["status"] = "ir_precursor"
        track["radar_confirmed"] = False
        track["is_potential_new_cell"] = stage in {"ir_watch_candidate", "ir_pre_cb", "ir_cb_precursor"}
        track["display_as_precursor"] = stage != "inactive"
        track["ir_only_precursor"] = 1.0

    track.setdefault("ir_score", 0.0)
    track.setdefault("height_stage", "low")
    track.setdefault("cloud_height_confidence", 0.0)
    track.setdefault("cloud_height_source", "default_fallback")
    track.setdefault("max_cloud_height_m", track.get("cloud_height_m", 0.0))
    # B253: first_height_alert_timestamp nur beim ersten Alarm setzen und danach fixieren.
    if "first_height_alert_timestamp" not in track:
        track["first_height_alert_timestamp"] = (
            ts if track.get("height_stage") not in (None, "", "low") else None
        )
    track.update(_forecast_fields(track))
    fresh = _age_min(track.get("source_timestamp")) <= float(_cfg("IR_WATCH_MAX_PUBLIC_AGE_MIN", IR_WATCH_MAX_PUBLIC_AGE_MIN))
    visible = bool(_cfg("IR_PUBLIC_WATCH_VISIBLE", IR_PUBLIC_WATCH_VISIBLE)) and fresh and track.get("status") != "inactive" and float(track.get("ir_score", 0.0) or 0.0) >= float(_cfg("IR_WATCH_MIN_SCORE", IR_WATCH_MIN_SCORE)) and not track.get("radar_confirmed")
    track["public_visible"] = bool(visible)
    track["public_label"] = _public_label(track.get("ir_stage"))
    track["warning_level"] = "none" if track.get("ir_stage") == "ir_watch_candidate" else "precursor"
    track["cb_alert_threshold_m"] = float(_cfg("CLOUD_HEIGHT_ALERT_THRESHOLD_M", CLOUD_HEIGHT_ALERT_THRESHOLD_M))

    if _lineage_enabled() and ensure_ir_track_cell_id is not None and not track.get("cell_id"):
        try:
            ensure_ir_track_cell_id(track, timestamp=ts)
        except Exception as exc:
            debug_log(f"[IR-TRACK] Zell-Lineage konnte nicht gesetzt werden: {exc}")
    return track

def _load_state() -> dict:
    if os.path.exists(_STATE_FILE):
        try:
            with open(_STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
            for track in state.get("tracks", {}).values():
                _normalize_ir_track(track)
            return state
        except Exception:
            pass
    return {"tracks": {}, "next_id": 0}


def _save_state(state: dict) -> None:
    os.makedirs(_SAVE_DIR, exist_ok=True)
    try:
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        debug_log(f"[IR-TRACK] State-Speicherfehler: {exc}")


def _ts_to_dt(ts: str) -> datetime | None:
    if not ts:
        return None
    for fmt in ("%Y-%m-%d_%H-%M-%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(ts).replace("+00:00", "Z"), fmt)
        except ValueError:
            continue
    return None


def _cell_obs_ts(cell: dict, fallback: str | None = None) -> str | None:
    return cell.get("observation_timestamp") or cell.get("source_timestamp") or cell.get("timestamp") or fallback


def _age_between_min(first_ts: str | None, last_ts: str | None) -> float:
    first = _ts_to_dt(first_ts)
    last = _ts_to_dt(last_ts)
    if first and last:
        return max(0.0, (last - first).total_seconds() / 60.0)
    return 0.0


def update_ir_tracking(new_cells: list, timestamp: str) -> list:
    """
    Aktualisiert das IR-Tracking mit den neuen Detektionen dieses Frames.

    Parameter
    ---------
    new_cells : Liste aus ir_cell_detection.detect_ir_cells()
    timestamp : YYYY-MM-DD_HH-MM-SS des aktuellen Frames

    Rückgabe  : Liste der aktiven Tracks (angereicherte IR-Cell-Dicts).
    """
    os.makedirs(_SAVE_DIR, exist_ok=True)
    state = _load_state()
    tracks = state.get("tracks", {})
    next_id = int(state.get("next_id", 0))

    dt_now = _ts_to_dt(timestamp)

    # ── Matching: neue Detektionen → bestehende Tracks ────────────────────────
    matched_new = set()   # Indizes in new_cells
    matched_old = set()   # track_ids

    # Greedy Nearest-Neighbor Matching
    for track_id, track in tracks.items():
        prev_lat = track.get("lat", 0.0)
        prev_lon = track.get("lon", 0.0)
        best_dist = _MAX_MATCH_DEG
        best_idx = None
        for i, cell in enumerate(new_cells):
            if i in matched_new:
                continue
            d = _deg_dist(prev_lat, prev_lon, cell["lat"], cell["lon"])
            if d < best_dist:
                best_dist = d
                best_idx = i
        if best_idx is not None:
            matched_new.add(best_idx)
            matched_old.add(track_id)
            cell = new_cells[best_idx]

            # Zeitdifferenz berechnen
            dt_prev_str = track.get("last_timestamp", timestamp)
            dt_prev = _ts_to_dt(dt_prev_str)
            dt_min = 15.0  # Default: MSG-Intervall
            if dt_now and dt_prev:
                delta = (dt_now - dt_prev).total_seconds() / 60.0
                if 1.0 < delta < 120.0:
                    dt_min = delta

            # Geschwindigkeit [Grad/min]
            vx = (cell["lon"] - prev_lon) / dt_min
            vy = (cell["lat"] - prev_lat) / dt_min

            # BT-Trend [K/min]:
            # MSG IR108 aktualisiert alle ~15 min. Wenn tiff_file sich nicht
            # geändert hat, ist bt_mean_k identisch → Trend würde 0 liefern
            # und den zuletzt berechneten Wert überschreiben.
            # Fix: Trend nur berechnen wenn neues TIFF, sonst letzten Wert behalten.
            _prev_tiff = track.get("tiff_file", "")
            _curr_tiff = cell.get("tiff_file", "")
            if _curr_tiff and _curr_tiff != _prev_tiff:
                # Neues TIFF → echten Trend über MSG-Intervall berechnen.
                # _tiff_dt = tatsächliches Intervall seit letztem TIFF-Wechsel.
                # Fallback: 15 min (MSG Full Earth Scan Intervall).
                _prev_bt_tiff = track.get("bt_mean_k_at_last_tiff", track.get("bt_mean_k", cell["bt_mean_k"]))
                _last_tiff_ts = track.get("last_tiff_timestamp")
                if _last_tiff_ts and dt_now:
                    _dt_tiff_prev = _ts_to_dt(_last_tiff_ts)
                    if _dt_tiff_prev:
                        _delta_tiff = (dt_now - _dt_tiff_prev).total_seconds() / 60.0
                        _tiff_dt = max(min(_delta_tiff, 60.0), 5.0)
                    else:
                        _tiff_dt = 15.0
                else:
                    _tiff_dt = 15.0
                bt_trend = round((cell["bt_mean_k"] - _prev_bt_tiff) / _tiff_dt, 3)
                # Zeitstempel und BT-Basiswert des aktuellen TIFFs speichern
                track["bt_mean_k_at_last_tiff"] = cell["bt_mean_k"]
                track["last_tiff_timestamp"] = timestamp
            else:
                # Gleiches TIFF → letzten berechneten Trend beibehalten
                bt_trend = track.get("bt_trend_k_per_min", 0.0)

            obs_ts = _cell_obs_ts(cell, timestamp)
            first_obs_ts = track.get("first_seen_observation_timestamp") or track.get("first_seen_timestamp") or obs_ts
            age_min = _age_between_min(first_obs_ts, obs_ts)

            # Anvil-Extension: Abstand Schwerpunkt zu kältestellem Pixel
            # Näherung: BT_min entspricht höchstem Punkt → Abstand via Fläche
            area_km2 = cell["area_px"] * 9.0  # ~3 km/px MSG → 9 km²/px
            anvil_km = (area_km2 ** 0.5) * 0.5  # grobe Abschätzung

            # Track aktualisieren
            track.update({
                "lat":              cell["lat"],
                "lon":              cell["lon"],
                "bt_min_k":         cell["bt_min_k"],
                "bt_mean_k":        cell["bt_mean_k"],
                "bt_trend_k_per_min": round(bt_trend, 3),
                "area_px":          cell["area_px"],
                "overshooting_top": cell["overshooting_top"],
                "cloud_height_m":   cell["cloud_height_m"],
                "cloud_height_confidence": cell.get("cloud_height_confidence", track.get("cloud_height_confidence", 0.0)),
                "cloud_height_source": cell.get("cloud_height_source", track.get("cloud_height_source", "default_fallback")),
                "max_cloud_height_m": max(float(track.get("max_cloud_height_m", 0.0) or 0.0), float(cell.get("cloud_height_m", 0.0) or 0.0)),
                "height_stage": cell.get("height_stage", track.get("height_stage", "low")),
                # B253: Striktes einmaliges Setzen — nie überschreiben wenn bereits gesetzt.
                "first_height_alert_timestamp": track.get("first_height_alert_timestamp") or (
                    obs_ts if (cell.get("height_stage") not in (None, "", "low")
                               and track.get("first_height_alert_timestamp") is None)
                    else None
                ),
                "ir_score": cell.get("ir_score", track.get("ir_score", 0.0)),
                "ir_stage": cell.get("ir_stage", track.get("ir_stage", "ir_watch_candidate")),
                "cape":             cell["cape"],
                "arome_li":         cell["arome_li"],
                "vx_deg_min":       round(vx, 6),
                "vy_deg_min":       round(vy, 6),
                "cloud_age_min":    round(age_min, 1),
                "anvil_extension_km": round(anvil_km, 1),
                "area_growth_px_per_min": round((cell.get("area_px", 0.0) - track.get("area_px", cell.get("area_px", 0.0))) / dt_min, 3),
                "area_growth_km2_per_min": round((cell.get("area_px", 0.0) - track.get("area_px", cell.get("area_px", 0.0))) * 9.0 / dt_min, 3),
                "cloud_height_trend_m_per_min": round((cell.get("cloud_height_m", 0.0) - track.get("cloud_height_m", cell.get("cloud_height_m", 0.0))) / dt_min, 3),
                "motion_quality":    "tracked",
                "first_seen_observation_timestamp": first_obs_ts,
                "last_seen_observation_timestamp": obs_ts,
                "observation_timestamp": obs_ts,
                "timestamp_source": cell.get("timestamp_source", track.get("timestamp_source")),
                "availability_latency_min": cell.get("availability_latency_min", track.get("availability_latency_min")),
                "source_layer": cell.get("source_layer", track.get("source_layer", "msg_fes:ir108")),
                "scan_mode": cell.get("scan_mode", track.get("scan_mode", "FES")),
                "source_timestamp":  obs_ts,
                "missing":          0,
                "last_timestamp":   obs_ts,
                "tiff_file":        cell["tiff_file"],
            })
            # B252: Stale-Observation-Prüfung: wenn tiff_file + observation_timestamp
            # identisch mit dem vorherigen Zyklus sind, erhöhe stale_obs_cycles.
            # Nach IR_MAX_STALE_OBS_CYCLES aufeinanderfolgenden eingefrorenen
            # Zyklen wird missing inkrementiert, damit der Track ausaltert.
            _prev_obs_ts = track.get("_prev_obs_ts_b252")
            _curr_obs_ts = obs_ts
            _prev_tiff_b252 = track.get("_prev_tiff_b252")
            _curr_tiff_b252 = cell.get("tiff_file", "")
            _same_obs = (_prev_obs_ts is not None
                         and _prev_obs_ts == _curr_obs_ts
                         and _prev_tiff_b252 == _curr_tiff_b252)
            if _same_obs:
                _stale = track.get("stale_obs_cycles", 0) + 1
                track["stale_obs_cycles"] = _stale
                try:
                    _max_stale = int(
                        runtime_config.get("IR_MAX_STALE_OBS_CYCLES", _IR_MAX_STALE_OBS_CYCLES_DEFAULT)
                        if runtime_config else _IR_MAX_STALE_OBS_CYCLES_DEFAULT
                    )
                except Exception:
                    _max_stale = _IR_MAX_STALE_OBS_CYCLES_DEFAULT
                if _stale >= _max_stale:
                    track["missing"] = track.get("missing", 0) + 1
                    track["motion_quality"] = "stale_obs"
                    debug_log(
                        f"[IR-TRACK] Track {track_id} Observation eingefroren "
                        f"(tiff={_curr_tiff_b252}, obs={_curr_obs_ts}, "
                        f"stale_cycles={_stale}) → missing={track['missing']}"
                    )
            else:
                track["stale_obs_cycles"] = 0
            # Merker für nächsten Zyklus
            track["_prev_obs_ts_b252"] = _curr_obs_ts
            track["_prev_tiff_b252"] = _curr_tiff_b252
        else:
            # Kein Match → missing erhöhen
            track["missing"] = track.get("missing", 0) + 1
            track["motion_quality"] = "stale"

    # ── Neue Tracks für ungematchte Detektionen ───────────────────────────────
    for i, cell in enumerate(new_cells):
        if i in matched_new:
            continue
        track_id = f"ir_{next_id}"
        next_id += 1
        obs_ts = _cell_obs_ts(cell, timestamp)
        tracks[track_id] = {
            "ir_id":                  track_id,
            "lat":                    cell["lat"],
            "lon":                    cell["lon"],
            "bt_min_k":               cell["bt_min_k"],
            "bt_mean_k":              cell["bt_mean_k"],
            "bt_mean_k_at_last_tiff": cell["bt_mean_k"],  # Basis für Trend-Berechnung
            "last_tiff_timestamp":    timestamp,           # Zeitpunkt des ersten TIFFs
            "bt_trend_k_per_min":     0.0,
            "area_px":                cell["area_px"],
            "overshooting_top":       cell["overshooting_top"],
            "cloud_height_m":         cell["cloud_height_m"],
            "cloud_height_confidence": cell.get("cloud_height_confidence", 0.0),
            "cloud_height_source":    cell.get("cloud_height_source", "default_fallback"),
            "cloud_height_trend_m_per_min": 0.0,
            "max_cloud_height_m":     cell.get("cloud_height_m", 0.0),
            "height_stage":           cell.get("height_stage", "low"),
            # B253: Nur setzen wenn height_stage eine CB-Stufe ist; sonst None.
            "first_height_alert_timestamp": (
                obs_ts if cell.get("height_stage") not in (None, "", "low") else None
            ),
            "ir_score":               cell.get("ir_score", 0.0),
            "ir_stage":               cell.get("ir_stage", "ir_watch_candidate"),
            "cape":                   cell["cape"],
            "arome_li":               cell["arome_li"],
            "vx_deg_min":             0.0,
            "vy_deg_min":             0.0,
            "cloud_age_min":          0.0,
            "anvil_extension_km":     0.0,
            "missing":                0,
            "last_timestamp":         obs_ts,
            "first_seen_observation_timestamp": obs_ts,
            "last_seen_observation_timestamp": obs_ts,
            "observation_timestamp": obs_ts,
            "timestamp_source": cell.get("timestamp_source"),
            "availability_latency_min": cell.get("availability_latency_min"),
            "source_layer": cell.get("source_layer", "msg_fes:ir108"),
            "scan_mode": cell.get("scan_mode", "FES"),
            "tiff_file":              cell["tiff_file"],
            "ir_only_precursor":      1.0,
            "radar_match_ids":        [],
            "first_seen_timestamp":  obs_ts,
            "source_timestamp":      obs_ts,
            "motion_quality":        "new",
            # B254: Steuerwind-Felder aus Detektion übernehmen (falls vorhanden)
            "wind_speed_700hPa":      float(cell.get("wind_speed_700hPa", 0.0) or 0.0),
            "wind_dir_cos":           float(cell.get("wind_dir_cos", 0.0) or 0.0),
            "wind_dir_sin":           float(cell.get("wind_dir_sin", 0.0) or 0.0),
        }
        _normalize_ir_track(tracks[track_id], default_timestamp=timestamp)

    # ── Abgestorbene Tracks löschen ───────────────────────────────────────────
    max_missing = int(IR_TRACK_MAX_MISSING)
    dead = [tid for tid, t in tracks.items() if t.get("missing", 0) > max_missing]
    for tid in dead:
        debug_log(f"[IR-TRACK] Track {tid} gelöscht (missing > {max_missing}).")
        del tracks[tid]

    # ── State persistieren ────────────────────────────────────────────────────
    for _track in tracks.values():
        _normalize_ir_track(_track, default_timestamp=timestamp)
    if _lineage_enabled() and ensure_ir_tracks_cell_ids is not None:
        try:
            ensure_ir_tracks_cell_ids(list(tracks.values()), timestamp=timestamp)
        except Exception as exc:
            debug_log(f"[IR-TRACK] Zell-Lineage-Migration vor Save fehlgeschlagen: {exc}")
    state["tracks"] = tracks
    state["next_id"] = next_id
    _save_state(state)

    active = [_normalize_ir_track(t, default_timestamp=timestamp) for t in tracks.values() if t.get("missing", 0) == 0]
    debug_log(f"[IR-TRACK] Aktive Tracks: {len(active)} / Gesamt: {len(tracks)}")
    return active


def mark_radar_matched_tracks(matched_ir_ids: list, radar_match_map: dict | None = None) -> None:
    """
    B109: Setzt ir_only_precursor=0.0 für alle IR-Tracks die radar-gematcht wurden
    und persistiert den aktualisierten State sofort.

    Muss von main.py NACH update_ir_tracking() und NACH Radar-Matching aufgerufen
    werden, damit api_risk_grid() einen konsistenten State liest.

    Parameters
    ----------
    matched_ir_ids : list
        Liste von IR-Track-IDs (ir_id) die aktuell radar-gematcht sind.
    """
    if not matched_ir_ids:
        return

    matched_set = {str(tid) for tid in matched_ir_ids if tid is not None}
    if not matched_set:
        return

    state = _load_state()
    tracks = state.get("tracks", {})
    updated = 0
    for track in tracks.values():
        if str(track.get("ir_id", "")) in matched_set:
            track["ir_only_precursor"] = 0.0
            track["radar_matched"] = True
            track["radar_confirmed"] = True
            track["is_potential_new_cell"] = False
            track["display_as_precursor"] = False
            track["status"] = "radar_confirmed"
            track["_type"] = "ir_precursor_cell"
            if track.get("ir_id") and not track.get("ir_track_id"):
                track["ir_track_id"] = track.get("ir_id")
            if radar_match_map is not None:
                track["radar_track_id"] = radar_match_map.get(track.get("ir_id"))
            _normalize_ir_track(track)
            updated += 1

    if updated > 0:
        state["tracks"] = tracks
        _save_state(state)
        debug_log(f"[IR-TRACK] B109: {updated} Radar-gematchte Tracks persistiert "
                  f"(ir_only_precursor=0.0).")


def load_active_ir_tracks() -> list:
    """
    Gibt alle aktiven IR-Tracks (missing == 0) aus dem letzten State zurück.
    Hilfsfunktion für app.py und main.py.
    """
    state = _load_state()
    tracks = state.get("tracks", {})
    active = [_normalize_ir_track(t) for t in tracks.values() if t.get("missing", 0) == 0]
    if _lineage_enabled() and ensure_ir_tracks_cell_ids is not None:
        try:
            missing_before = any(isinstance(t, dict) and not t.get("cell_id") for t in active)
            ensure_ir_tracks_cell_ids(active)
            if missing_before:
                state["tracks"] = tracks
                _save_state(state)
        except Exception as exc:
            debug_log(f"[IR-TRACK] Zell-Lineage-Migration beim Laden fehlgeschlagen: {exc}")
    return active


if __name__ == "__main__":
    from ir_cell_detection import load_latest_ir_cells
    cells = load_latest_ir_cells()
    from datetime import datetime as _dt
    ts = _dt.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
    tracks = update_ir_tracking(cells, ts)
    print(f"[IR-TRACK] {len(tracks)} aktive Tracks")
    for t in tracks:
        print(f"  {t['ir_id']}: lat={t['lat']} lon={t['lon']} "
              f"bt_min={t['bt_min_k']} K age={t['cloud_age_min']} min")
