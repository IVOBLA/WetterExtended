# convective_outlook.py
"""
Berechnet aus atmosphere_timeseries.json (fetch_outlook_series.py) 12 stuendliche
Risiko-/Schwere-Raster ueber Kaernten und schreibt train_data/forecast/outlook_12h.json.

Pro Grid-Zelle und Stunde:
  risk      : 1..3 (Gelb/Orange/Rot)
  severity  : {rain_mm_h, gust_kmh, hail_index, hail_cat}  (physikalische Proxys)
  info      : {dominant, cape, li, cin, pw, ship}

Zutaten -> Heuristik. Zusaetzlich klimatologischer Attraktor-Prior aus Zell-Historie
(Frequenzkarte je Grobraster + Monat). KEIN externer API-Call.
"""

import os
import json
import glob
import math
import time
from datetime import datetime, timezone

from config import BBOX_KAERNTEN_EXTENDED, SAVE_PATHS
from debug_utils import debug_log
import runtime_config

_FORECAST_DIR = os.path.join(
    os.path.dirname(SAVE_PATHS.get("evaluation", "train_data/evaluation/").rstrip("/")),
    "forecast",
)
_SERIES_FILE   = os.path.join(_FORECAST_DIR, "atmosphere_timeseries.json")
_OUT_FILE      = os.path.join(_FORECAST_DIR, "outlook_12h.json")
_ATTRACTOR_FILE = os.path.join(_FORECAST_DIR, "attractor_map.json")

_RISK_COLORS = {1: "#facc15", 2: "#f97316", 3: "#dc2626"}
_ATTR_STEP   = 0.1          # Grobraster fuer Attraktor (~10 km)
_ATTR_MAX_AGE_H = 24


def _f(v, d=0.0):
    try:
        x = float(v)
        return d if (math.isnan(x) or math.isinf(x)) else x
    except (TypeError, ValueError):
        return d


def _bbox_limits():
    b = runtime_config.get("BBOX_KAERNTEN_EXTENDED", BBOX_KAERNTEN_EXTENDED)
    if isinstance(b, dict):
        return _f(b.get("south"), 46.36), _f(b.get("north"), 47.18), _f(b.get("west"), 12.60), _f(b.get("east"), 15.20)
    if isinstance(b, (list, tuple)) and len(b) == 4:
        return _f(b[0], 46.36), _f(b[1], 47.18), _f(b[2], 12.60), _f(b[3], 15.20)
    return 46.36, 47.18, 12.60, 15.20


def _hav(la1, lo1, la2, lo2):
    R = 6371.0
    dlat = math.radians(la2 - la1); dlon = math.radians(lo2 - lo1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(la1)) * math.cos(math.radians(la2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ---------------------------------------------------------------------------
# Klimatologischer Attraktor-Prior aus Zell-Historie
# ---------------------------------------------------------------------------

def _build_attractor():
    """Frequenzkarte: wie oft trat je Grobraster-Zelle und Monat eine Gewitterzelle auf."""
    counts = {}
    files = sorted(glob.glob(os.path.join(SAVE_PATHS["objects"], "*.json")))
    for p in files:
        try:
            month = int(os.path.basename(p)[5:7])
            with open(p, encoding="utf-8") as f:
                objs = json.load(f)
        except Exception:
            continue
        for o in objs if isinstance(objs, list) else []:
            lat = o.get("lat"); lon = o.get("lon")
            if lat is None or lon is None:
                continue
            gl = round(_f(lat) / _ATTR_STEP) * _ATTR_STEP
            go = round(_f(lon) / _ATTR_STEP) * _ATTR_STEP
            key = f"{gl:.2f}|{go:.2f}|{month}"
            counts[key] = counts.get(key, 0) + 1
    mx = max(counts.values()) if counts else 1
    payload = {"built_at": time.time(), "step": _ATTR_STEP, "max": mx, "counts": counts}
    os.makedirs(_FORECAST_DIR, exist_ok=True)
    with open(_ATTRACTOR_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    debug_log(f"[OUTLOOK] Attraktor-Karte gebaut: {len(counts)} Zellen, max={mx}")
    return payload


def _load_attractor():
    if os.path.exists(_ATTRACTOR_FILE):
        age_h = (time.time() - os.path.getmtime(_ATTRACTOR_FILE)) / 3600.0
        if age_h < _ATTR_MAX_AGE_H:
            try:
                with open(_ATTRACTOR_FILE, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return _build_attractor()


def _attractor_prior(attr, lat, lon, month):
    counts = attr.get("counts", {}); mx = max(attr.get("max", 1), 1)
    gl = round(lat / _ATTR_STEP) * _ATTR_STEP
    go = round(lon / _ATTR_STEP) * _ATTR_STEP
    c = counts.get(f"{gl:.2f}|{go:.2f}|{month}", 0)
    return min(c / mx, 1.0)   # 0..1


# ---------------------------------------------------------------------------
# Zutaten -> Schwere/Risiko
# ---------------------------------------------------------------------------

def _ship(cape, t500, lapse, shear_kmh):
    """SHIP-aehnlicher Hagel-Index (vereinfachte Stull-Form, ohne MixR)."""
    if cape <= 0 or shear_kmh <= 0:
        return 0.0
    shear_ms = shear_kmh / 3.6
    val = (cape * max(lapse, 0.0) * max(-t500, 0.0) * shear_ms) / (44.0e6 / 50.0)
    return round(val, 2)


def _diurnal_weight(valid_iso):
    try:
        hh = int(valid_iso[11:13])
    except Exception:
        return 1.0
    # Konvektions-Tagesgang: Maximum ~16 Uhr lokal, Minimum nachts.
    return 0.6 + 0.4 * max(0.0, math.cos(math.radians((hh - 16) * 15.0)))


def _cell_severity(s, attr_prior, valid_iso):
    cape = _f(s.get("cape")); cin = _f(s.get("convective_inhibition"))
    li   = _f(s.get("lifted_index"))
    # PW: primär aus Series (falls via GFS verfügbar), sonst klimatologischer
    # Default 25 mm für Kärnten bei konvektiven Bedingungen (cape >= 200 J/kg).
    # Hintergrund: fetch_outlook_series.py nutzt ICON — kein precipitable_water.
    # fetch_openmeteo_extended.py liefert PW per Zelle als total_column_integrated_water_vapour.
    pw = _f(s.get("precipitable_water")) or _f(s.get("total_column_integrated_water_vapour"))
    if pw <= 0.0 and cape >= 200.0:
        pw = 25.0   # Klimatologischer Mittelwert Kärnten bei konvektiver Aktivität [mm]
    t500 = _f(s.get("temperature_500hPa")); t700 = _f(s.get("temperature_700hPa"))
    fl   = _f(s.get("freezing_level_height"))
    gust = _f(s.get("wind_gusts_10m"))
    w10  = _f(s.get("wind_speed_10m")); w700 = _f(s.get("windspeed_700hPa"))
    lapse = (t700 - t500) / 3.0 if (t500 or t700) else 0.0
    shear = abs(w700 - w10)
    diur = _diurnal_weight(valid_iso)

    # Instabilitaets-Score 0..1 (CAPE + LI, gedeckelt durch CIN)
    inst = min(cape / 2000.0, 1.0) * 0.6 + min(max(-li, 0.0) / 6.0, 1.0) * 0.4
    cap_factor = 1.0 - min(max(-cin, 0.0) / 150.0, 0.7)   # starke CIN daempft
    base = inst * cap_factor * diur
    base = min(base * (0.7 + 0.3 * attr_prior), 1.0)      # Attraktor-Prior moduliert

    # Schwere-Proxys
    rain = round(min(pw, 50.0) * min(cape / 1500.0, 2.0) * 1.2, 1)        # mm/h grob
    gust_pred = round(max(gust, w10 + min(cape / 100.0, 40.0) * (lapse / 7.0 if lapse > 0 else 0)), 1)
    ship = _ship(cape, t500, lapse, shear)
    hail_index = round(ship * (1.0 if fl < 3600 else 0.5), 2)             # tiefe Gefriergrenze hilft
    hail_cat = "gross" if hail_index >= 1.5 else ("klein" if hail_index >= 0.8 else "kein")

    # Risiko 1..3
    # B62: gust_pred >= 70 nur als Trigger wenn minimale Konvektionsinstabilität
    # vorhanden (inst >= 0.05 ≈ CAPE > ~100 J/kg oder LI < -0.3).
    # Verhindert Falschalarme durch nicht-konvektive Böen (Föhn, Kaltfront ohne Gewitter).
    if base >= 0.6 or hail_index >= 1.5 or rain >= 35:
        risk = 3
    elif base >= 0.35 or hail_index >= 0.8 or rain >= 18 or (gust_pred >= 70 and inst >= 0.05):
        risk = 2
    elif base >= 0.15:
        risk = 1
    else:
        risk = 0

    dominant = "hagel" if hail_index >= 0.8 else ("regen" if rain >= 18 else ("boe" if gust_pred >= 70 else "instabilitaet"))
    return risk, {
        "rain_mm_h": rain, "gust_kmh": gust_pred,
        "hail_index": hail_index, "hail_cat": hail_cat,
    }, {
        "dominant": dominant, "cape": round(cape), "li": round(li, 1),
        "cin": round(cin), "pw": round(pw, 1), "ship": ship,
    }


# ---------------------------------------------------------------------------
# Hauptfunktion
# ---------------------------------------------------------------------------

def compute_outlook():
    if not os.path.exists(_SERIES_FILE):
        debug_log("[OUTLOOK] Keine atmosphere_timeseries.json — erst Prompt-7-Job laufen lassen")
        return {"hours": []}

    with open(_SERIES_FILE, encoding="utf-8") as f:
        series = json.load(f)
    points = series.get("points", [])
    if not points:
        return {"hours": []}

    attr = _load_attractor()
    lat_min, lat_max, lon_min, lon_max = _bbox_limits()
    step = _f(runtime_config.get("RISK_GRID_STEP_DEG", 0.05), 0.05)

    # Grid-Punkte vorbereiten
    grid = []
    la = lat_min
    while la <= lat_max + 1e-9:
        lo = lon_min
        while lo <= lon_max + 1e-9:
            grid.append((round(la, 4), round(lo, 4)))
            lo += step
        la += step

    n_hours = min(p_len for p_len in [len(p.get("series", [])) for p in points]) if points else 0

    # B341: offset_h/valid relativ zur aktuellen Uhrzeit neu ankern statt
    # 1:1 aus dem Serien-Index zu uebernehmen. `valid` ist naive
    # Europe/Vienna-Lokalzeit (fetch_outlook_series.py), daher Vergleich
    # gegen datetime.now() (im Projekt durchgaengig naive lokale Zeit).
    _now_local_str = datetime.now().strftime("%Y-%m-%dT%H:%M")
    hours_out = []
    _offset_out = 0
    for h in range(1, min(n_hours, 13)):   # +1..+12 h (Serien-Index)
        valid = points[0]["series"][h].get("valid", "")
        if valid and valid < _now_local_str:
            # Bereits verstrichene Stunde (z. B. veralteter 429-Fallback aus
            # fetch_outlook_series.py._load_fallback) — nicht ausgeben.
            continue
        _offset_out += 1
        month = int(valid[5:7]) if len(valid) >= 7 else datetime.now().month
        cells = []
        for (la, lo) in grid:
            # naechster Zeitreihen-Punkt
            best, bestd = None, 1e9
            for p in points:
                d = _hav(la, lo, p["lat"], p["lon"])
                if d < bestd:
                    bestd, best = d, p
            if best is None or h >= len(best["series"]):
                continue
            s = best["series"][h]
            prior = _attractor_prior(attr, la, lo, month)
            risk, sev, info = _cell_severity(s, prior, valid)
            if risk <= 0:
                continue
            cells.append({"lat": la, "lon": lo, "risk": risk,
                          "color": _RISK_COLORS[risk], "severity": sev, "info": info})
        hours_out.append({"offset_h": _offset_out, "valid": valid, "cells": cells})

    if not hours_out:
        # B341: Serie vollstaendig veraltet (alle Stunden liegen bereits in
        # der Vergangenheit) — bestehenden outlook_12h.json NICHT mit einem
        # leeren/irrefuehrenden Payload ueberschreiben.
        return {"hours": [], "stale": True}

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "grid_step": step, "horizon_h": len(hours_out), "hours": hours_out,
    }
    os.makedirs(_FORECAST_DIR, exist_ok=True)
    tmp = _OUT_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp, _OUT_FILE)
    debug_log(f"[OUTLOOK] {len(hours_out)} Stunden-Raster geschrieben -> {_OUT_FILE}")
    return payload


def load_outlook():
    if os.path.exists(_OUT_FILE):
        try:
            with open(_OUT_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"hours": []}


if __name__ == "__main__":
    r = compute_outlook()
    print("Stunden:", len(r.get("hours", [])))
