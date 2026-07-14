# track_statistics.py
"""
P-S01: Track-Lifecycle-Statistik.

Schreibt beim endgültigen Tod einer Zelle genau EINEN abschließenden
JSONL-Datensatz nach train_data/evaluation/track_ends.jsonl und stellt
die zirkuläre Richtungsmathematik bereit.

Zirkulärer Mittelwert ist PFLICHT: 350° und 10° mitteln zu 0°, nicht 180°.
"""

import json
import math
import os
from datetime import datetime

try:
    from debug_utils import debug_log
except Exception:
    def debug_log(message):
        print(message)

try:
    from config import SAVE_PATHS
except Exception:
    SAVE_PATHS = {"evaluation": "train_data/evaluation"}

_TS_FMT = "%Y-%m-%d_%H-%M-%S"


def track_ends_path() -> str:
    """Pfad der track_ends.jsonl (Live-Daten, nicht Backfill)."""
    return os.path.join(
        SAVE_PATHS.get("evaluation", "train_data/evaluation"),
        "track_ends.jsonl",
    )


def circular_mean_deg(angles_deg, weights=None):
    """
    Zirkulärer Mittelwert von Winkeln in Grad (0..360, meteorologisch beliebig).

    Rückgabe: (mean_deg, consistency)
      mean_deg    : float 0..360 oder None wenn keine Eingabe / Resultante 0
      consistency : Resultantenlänge R in 0..1
                    (1.0 = perfekt geradlinig, 0.0 = richtungslos)

    Beispiel: circular_mean_deg([350.0, 10.0]) -> (0.0, ~0.985)
    """
    angles = [a for a in (angles_deg or []) if a is not None]
    if not angles:
        return None, 0.0
    if weights is None:
        weights = [1.0] * len(angles)
    if len(weights) != len(angles):
        raise ValueError("weights muss gleiche Länge wie angles_deg haben")
    w_sum = float(sum(weights))
    if w_sum <= 0.0:
        return None, 0.0
    s = sum(w * math.sin(math.radians(a)) for a, w in zip(angles, weights))
    c = sum(w * math.cos(math.radians(a)) for a, w in zip(angles, weights))
    r = math.hypot(s, c) / w_sum
    if r < 1e-9:
        return None, 0.0
    mean = math.degrees(math.atan2(s, c)) % 360.0
    return round(mean, 1), round(r, 3)


def circular_mean_from_sums(sum_sin: float, sum_cos: float, w_sum: float):
    """Wie circular_mean_deg, aber aus laufenden Summen (inkrementelle Tracks)."""
    if w_sum <= 0.0:
        return None, 0.0
    r = math.hypot(sum_sin, sum_cos) / w_sum
    if r < 1e-9:
        return None, 0.0
    mean = math.degrees(math.atan2(sum_sin, sum_cos)) % 360.0
    return round(mean, 1), round(r, 3)


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Anfangskurs (Bewegungsrichtung NACH, 0°=N, 90°=O) von Punkt 1 nach Punkt 2."""
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine-Distanz in km."""
    r_earth = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * r_earth * math.asin(min(1.0, math.sqrt(a)))


def _parse_ts(ts_str):
    try:
        return datetime.strptime(ts_str, _TS_FMT)
    except (ValueError, TypeError):
        return None


def _safe_float(v, default=0.0):
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def accumulate_severity_maxima(objects) -> None:
    """
    P-S01: Schreibt Schwere-/Hagel-/Blitz-Maxima ZURUECK in tracking_memory.

    Wird in main.py NACH assign_severity()/Gust-Anreicherung aufgerufen, weil
    diese Felder erst dort am Objekt existieren (nicht in object_tracking).
    Explizites Write-back per ID — keine Annahme über Dict-Referenzen.
    """
    try:
        import object_tracking as _ot
        mem = _ot.tracking_memory
    except Exception as exc:
        debug_log(f"[P-S01] accumulate_severity_maxima übersprungen: {exc}")
        return
    _hail_rank = {"keiner": 0, "klein": 1, "gross": 2}
    for obj in objects or []:
        oid = obj.get("id")
        if not oid or oid not in mem:
            continue
        t = mem[oid]
        # Schwere wird von assign_severity unter obj["severity"] abgelegt:
        #   level    : 1..4  (1=schwach, 2=mittel, 3=stark, 4=sehr stark)
        #   hail_cat : "keiner" | "klein" | "gross"
        #   hail_prob: 0..1
        sev = obj.get("severity") or {}
        lvl = sev.get("level")
        if lvl is not None:
            try:
                t["max_severity_level"] = max(int(lvl), int(t.get("max_severity_level", 0) or 0))
            except (TypeError, ValueError):
                pass
        cat = sev.get("hail_cat")
        if cat in _hail_rank:
            prev_cat = t.get("max_hail_cat", "keiner")
            if _hail_rank[cat] > _hail_rank.get(prev_cat, 0):
                t["max_hail_cat"] = cat
        hp = _safe_float(sev.get("hail_prob"), 0.0)
        if hp > _safe_float(t.get("max_hail_prob"), 0.0):
            t["max_hail_prob"] = hp
        ln = _safe_float(obj.get("lightning_count_10km"), 0.0)
        if ln > _safe_float(t.get("max_lightning_10km"), 0.0):
            t["max_lightning_10km"] = ln


def accumulate_station_encounter(objects) -> None:
    """
    P73: Schreibt die letzte "Stationsbegegnung" (Zelle war im engen
    Bereich einer TAWES-Station, siehe STATION_ENCOUNTER_MAX_KM) ZURUECK
    in tracking_memory, damit sie ueber den gesamten Lebenszyklus der
    Zelle erhalten bleibt — auch nachdem die Zelle die Station laengst
    wieder verlassen hat. Ziel: abschaetzen, mit welchen Boeen bei der
    Zelle zu rechnen ist, anhand der letzten tatsaechlichen Messung in
    ihrer Naehe.

    Wird in main.py NACH der TAWES-Anreicherung aufgerufen (Feld
    obj["last_station_encounter"] existiert erst dort). Explizites
    Write-back per ID — keine Annahme über Dict-Referenzen (siehe
    accumulate_severity_maxima()).
    """
    try:
        import object_tracking as _ot
        mem = _ot.tracking_memory
    except Exception as exc:
        debug_log(f"[P73] accumulate_station_encounter übersprungen: {exc}")
        return
    for obj in objects or []:
        oid = obj.get("id")
        if not oid or oid not in mem:
            continue
        encounter = obj.get("last_station_encounter")
        if encounter is not None:
            mem[oid]["last_station_encounter"] = encounter


def write_track_end(obj: dict, end_reason: str, end_detected_ts: str) -> bool:
    """
    Schreibt den abschließenden Lifecycle-Datensatz für einen Track.

    Idempotent pro Track-Objekt: setzt obj["_track_end_written"]=True und
    schreibt bei erneutem Aufruf nichts (verhindert Doppel-Logging, z.B.
    Merge-Parent der danach auch durch die Missing-Schleife läuft).

    Rückgabe: True wenn geschrieben, False wenn übersprungen/Fehler.
    """
    if not isinstance(obj, dict):
        return False
    if obj.get("_track_end_written"):
        return False
    obj["_track_end_written"] = True

    first_seen = obj.get("first_seen")
    history = obj.get("history") or []
    last_seen = None
    if history and isinstance(history[-1], dict):
        last_seen = history[-1].get("timestamp")
    if not last_seen:
        last_seen = first_seen

    lifetime_min = None
    dt_first = _parse_ts(first_seen)
    dt_last = _parse_ts(last_seen)
    if dt_first and dt_last and dt_last >= dt_first:
        lifetime_min = round((dt_last - dt_first).total_seconds() / 60.0, 1)

    mean_dir, consistency = circular_mean_from_sums(
        _safe_float(obj.get("dir_sum_sin")),
        _safe_float(obj.get("dir_sum_cos")),
        _safe_float(obj.get("dir_km_sum")),
    )

    speed_n = _safe_float(obj.get("speed_n"))
    mean_speed = (
        round(_safe_float(obj.get("speed_sum_kmh")) / speed_n, 1) if speed_n > 0 else None
    )

    start_lat = start_lon = None
    path_points = obj.get("path_points") or []
    if path_points and isinstance(path_points[0], (list, tuple)) and len(path_points[0]) >= 2:
        start_lat = round(float(path_points[0][0]), 4)
        start_lon = round(float(path_points[0][1]), 4)

    record = {
        "id":                  obj.get("id"),
        "first_seen":          first_seen,
        "last_seen":           last_seen,
        "end_detected_ts":     end_detected_ts,
        "lifetime_min":        lifetime_min,
        "total_active_frames": int(obj.get("total_active_frames", 0) or 0),
        "end_reason":          end_reason,
        "start_lat":           start_lat,
        "start_lon":           start_lon,
        "end_lat":             round(_safe_float(obj.get("lat")), 4) if obj.get("lat") is not None else None,
        "end_lon":             round(_safe_float(obj.get("lon")), 4) if obj.get("lon") is not None else None,
        "track_length_km":     round(_safe_float(obj.get("path_length_km")), 2),
        "mean_dir_deg":        mean_dir,
        "dir_consistency":     consistency,
        "segment_dirs_deg":    list(obj.get("seg_dirs_deg") or []),
        "path_points":         [[round(float(p[0]), 4), round(float(p[1]), 4)] for p in path_points],
        "mean_speed_kmh":      mean_speed,
        "stationary_frames":   int(obj.get("stationary_frames", 0) or 0),
        "max_core_ratio":      round(_safe_float(obj.get("max_core_ratio")), 3),
        "max_severity_level":  obj.get("max_severity_level"),
        "max_hail_cat":        obj.get("max_hail_cat", "keiner"),
        "max_hail_prob":       round(_safe_float(obj.get("max_hail_prob")), 3),
        "max_lightning_10km":  int(_safe_float(obj.get("max_lightning_10km"))),
        "lineage":             obj.get("lineage"),
        "parents":             list(obj.get("parents") or []),
        "children":            list(obj.get("children") or []),
        # P73: letzte Stationsbegegnung (Wind/Böe/Richtung real gemessen,
        # als die Zelle zuletzt im Bereich einer TAWES-Station war).
        "last_station_encounter": obj.get("last_station_encounter"),
    }

    path = track_ends_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False)
            f.write("\n")
        return True
    except Exception as exc:
        debug_log(f"[P-S01] track_ends Schreibfehler ({obj.get('id')}): {exc}")
        return False
