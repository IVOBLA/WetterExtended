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

from config import SAVE_PATHS, IR_TRACK_MAX_MISSING
from debug_utils import debug_log

_SAVE_DIR   = SAVE_PATHS.get("ir_cells", "train_data/ir_cells/")
_STATE_FILE = os.path.join(_SAVE_DIR, "ir_track_state.json")

# Maximaler Abstand [Grad] zweier IR-Cells zwischen Frames für ein Match.
# MSG 15 min × max. 120 km/h Verlagerung ÷ 111 km/Grad ≈ 0.27°
_MAX_MATCH_DEG = 0.30


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1-a))


def _deg_dist(lat1, lon1, lat2, lon2) -> float:
    """Grobe Gradabstand-Näherung (kein Haversine — nur für Matching)."""
    return ((lat2 - lat1)**2 + (lon2 - lon1)**2) ** 0.5


def _load_state() -> dict:
    if os.path.exists(_STATE_FILE):
        try:
            with open(_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
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
    for fmt in ("%Y-%m-%d_%H-%M-%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    return None


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

            # Alter des Tracklets
            age_min = track.get("cloud_age_min", 0.0) + dt_min

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
                "cape":             cell["cape"],
                "arome_li":         cell["arome_li"],
                "vx_deg_min":       round(vx, 6),
                "vy_deg_min":       round(vy, 6),
                "cloud_age_min":    round(age_min, 1),
                "anvil_extension_km": round(anvil_km, 1),
                "missing":          0,
                "last_timestamp":   timestamp,
                "tiff_file":        cell["tiff_file"],
            })
        else:
            # Kein Match → missing erhöhen
            track["missing"] = track.get("missing", 0) + 1

    # ── Neue Tracks für ungematchte Detektionen ───────────────────────────────
    for i, cell in enumerate(new_cells):
        if i in matched_new:
            continue
        track_id = f"ir_{next_id}"
        next_id += 1
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
            "cape":                   cell["cape"],
            "arome_li":               cell["arome_li"],
            "vx_deg_min":             0.0,
            "vy_deg_min":             0.0,
            "cloud_age_min":          0.0,
            "anvil_extension_km":     0.0,
            "missing":                0,
            "last_timestamp":         timestamp,
            "tiff_file":              cell["tiff_file"],
            "ir_only_precursor":      1.0,
            "radar_match_ids":        [],
        }

    # ── Abgestorbene Tracks löschen ───────────────────────────────────────────
    max_missing = int(IR_TRACK_MAX_MISSING)
    dead = [tid for tid, t in tracks.items() if t.get("missing", 0) > max_missing]
    for tid in dead:
        debug_log(f"[IR-TRACK] Track {tid} gelöscht (missing > {max_missing}).")
        del tracks[tid]

    # ── State persistieren ────────────────────────────────────────────────────
    state["tracks"] = tracks
    state["next_id"] = next_id
    _save_state(state)

    active = [t for t in tracks.values() if t.get("missing", 0) == 0]
    debug_log(f"[IR-TRACK] Aktive Tracks: {len(active)} / Gesamt: {len(tracks)}")
    return active


def load_active_ir_tracks() -> list:
    """
    Gibt alle aktiven IR-Tracks (missing == 0) aus dem letzten State zurück.
    Hilfsfunktion für app.py und main.py.
    """
    state = _load_state()
    return [t for t in state.get("tracks", {}).values() if t.get("missing", 0) == 0]


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
