# compute_convective_indices.py
"""
Reine Berechnung konvektiver Indizes aus bereits vorhandenen Objekt-Feldern.

KEINE Netzwerk-Aufrufe. Alle Eingangsdaten muessen vorher auf den Objekten
gesetzt worden sein (durch fetch_arome_openmeteo, fetch_700hpa_wind_per_object,
fetch_openmeteo_extended, fetch_synoptic_features, assign_cape).

Berechnet:
  - lapse_700_500   : Lapse Rate 700-500 hPa (Grad C / km)
  - shear_0_6km_*   : Scherungsvektor zwischen 10m und 500hPa (~5.5 km AGL)
  - mixr            : Mischungsverhaeltnis aus Taupunkt
  - ship_index      : Significant Hail Parameter (Stull-Form)
  - lightning_jump  : Blitzraten-Anstieg (Indikator fuer Intensivierung)
  - hail_prob2      : SHIP-basierte Hagelwahrscheinlichkeit 0.0-1.0

Quellen:
  - SHIP-Form: Stull, "Practical Meteorology", Kap. Thunderstorm Hazards
  - Lapse Rate 700-500: hypsometrische Naeherung Delta_z = 3.0 km
  - Lightning Jump: Schultz et al., 2009 (Sigma-Verfahren stark vereinfacht)
"""
from __future__ import annotations

import glob
import json
import math
import os
from datetime import datetime, timedelta

from config import SAVE_PATHS
from debug_utils import debug_log


# ---------------------------------------------------------------------------
# Konstanten
# ---------------------------------------------------------------------------
_DELTA_Z_700_500_KM = 3.0   # hypsometrische Naeherung, mittlere Breiten
_P_SFC_HPA          = 1013.0  # Standard-Bodendruck fuer Mischungsverhaeltnis
_LIGHTNING_LOOKBACK_MIN = 15  # Zeitfenster fuer Lightning-Jump-Vergleich
_LIGHTNING_NOW_MIN      = 5   # Aktuelle Rate aus letzten 5 Min


# ---------------------------------------------------------------------------
# Hilfsfunktionen — saturation vapor pressure, mixing ratio
# ---------------------------------------------------------------------------
def _sat_vapor_pressure_hpa(td_c: float) -> float:
    """Saettigungsdampfdruck nach Magnus-Tetens (hPa)."""
    return 6.112 * math.exp(17.67 * td_c / (td_c + 243.5))


def _mixing_ratio_g_kg(td_c: float, p_hpa: float = _P_SFC_HPA) -> float:
    """Mischungsverhaeltnis aus Taupunkt und Druck (g/kg)."""
    if td_c <= -50.0 or p_hpa <= 0:
        return 0.0
    e = _sat_vapor_pressure_hpa(td_c)
    if e >= p_hpa:
        return 0.0
    return 621.97 * e / (p_hpa - e)


# ---------------------------------------------------------------------------
# Lapse Rate 700-500 hPa
# ---------------------------------------------------------------------------
def _compute_lapse_700_500(obj: dict) -> float:
    """
    Lapse Rate 700-500 hPa in Grad C / km.
    Annahme: Delta_z ~ 3.0 km in mittleren Breiten (hypsometrische Naeherung).
    """
    t700 = float(obj.get("t700_c", 0.0) or 0.0)
    t500 = float(obj.get("t500_c", 0.0) or 0.0)
    if t700 == 0.0 and t500 == 0.0:
        return 0.0
    return round((t700 - t500) / _DELTA_Z_700_500_KM, 2)


# ---------------------------------------------------------------------------
# 0-6-km-Scherung (eigentlich 10 m -> 500 hPa, ca. 5.5 km AGL)
# ---------------------------------------------------------------------------
def _compute_shear_0_6km(obj: dict) -> tuple[float, float, float]:
    """
    Differenzvektor 10m-Wind (AROME icon_d2) zu 500-hPa-Wind (icon_global).
    Rueckgabe: (speed_kmh, cos_dir, sin_dir).

    500 hPa entspricht in mittleren Breiten ca. 5500 m AGL — die nominelle
    'Deep-Layer-Shear' der Literatur (0-6 km) ist damit gut approximiert.
    """
    # Bodenwind (10 m) aus AROME icon_d2
    sfc_speed   = float(obj.get("arome_ff10m", 0.0) or 0.0)
    sfc_dir_cos = float(obj.get("arome_dd_cos", 0.0) or 0.0)
    sfc_dir_sin = float(obj.get("arome_dd_sin", 0.0) or 0.0)

    # 500-hPa-Wind aus icon_global (von fetch_openmeteo_extended.py)
    top_speed   = float(obj.get("wind_speed_500hPa", 0.0) or 0.0)
    top_dir_cos = float(obj.get("wind_dir_500_cos", 0.0) or 0.0)
    top_dir_sin = float(obj.get("wind_dir_500_sin", 0.0) or 0.0)

    u_sfc = sfc_speed * sfc_dir_cos
    v_sfc = sfc_speed * sfc_dir_sin
    u_top = top_speed * top_dir_cos
    v_top = top_speed * top_dir_sin

    du = u_top - u_sfc
    dv = v_top - v_sfc
    speed = math.hypot(du, dv)
    angle = math.atan2(dv, du) if speed > 0 else 0.0

    return (
        round(speed, 2),
        round(math.cos(angle), 4),
        round(math.sin(angle), 4),
    )


# ---------------------------------------------------------------------------
# SHIP-Index (Significant Hail Parameter)
# ---------------------------------------------------------------------------
def _compute_ship(obj: dict, lapse: float, shear_kmh: float, mixr: float) -> float:
    """
    SHIP-Form nach Stull, Practical Meteorology:
        SHIP = (CAPE * MIXR * Lapse * (-T500) * Shear) / 44e6

    Einheiten:
      CAPE   : J/kg
      MIXR   : g/kg
      Lapse  : Grad C / km
      T500   : Grad C (negativ, weil mittlere Troposphaere)
      Shear  : m/s  (Umrechnung von km/h notwendig)
    Rueckgabe: dimensionslos, typ. 0-4.
    """
    cape  = float(obj.get("cape", 0.0) or 0.0)
    t500  = float(obj.get("t500_c", 0.0) or 0.0)
    if cape <= 0 or mixr <= 0 or lapse <= 0 or t500 >= 0:
        return 0.0
    shear_ms = shear_kmh / 3.6
    ship = (cape * mixr * lapse * (-t500) * shear_ms) / 44e6
    return round(max(ship, 0.0), 3)


# ---------------------------------------------------------------------------
# Lightning Jump
# ---------------------------------------------------------------------------
def _compute_lightning_jump(obj: dict, now: datetime | None = None) -> float:
    """
    Verhaeltnis Blitzrate jetzt / Blitzrate vor _LIGHTNING_LOOKBACK_MIN.
    Liest gespeicherte Object-Files (kein API-Call).

    Rueckgabe: 1.0 = stabil. >2.0 = signifikanter Anstieg (Hagel/Tornado-Indikator).
    """
    lat = obj.get("lat")
    lon = obj.get("lon")
    if lat is None or lon is None:
        return 1.0
    now = now or datetime.utcnow()
    obj_dir = SAVE_PATHS.get("objects", "train_data/objects/").rstrip("/")
    files = sorted(glob.glob(os.path.join(obj_dir, "*.json")))
    if len(files) < 3:
        return 1.0

    target_old = now - timedelta(minutes=_LIGHTNING_LOOKBACK_MIN)
    older_file = None
    for path in reversed(files[:-1]):
        try:
            ts_str = os.path.basename(path).replace(".json", "")
            ts = datetime.strptime(ts_str, "%Y-%m-%d_%H-%M-%S")
            if ts <= target_old:
                older_file = path
                break
        except Exception:
            continue
    if older_file is None:
        return 1.0

    try:
        with open(older_file, encoding="utf-8") as f:
            older = json.load(f)
    except Exception:
        return 1.0

    # naechstgelegene Zelle im alten Frame finden (innerhalb 10 km)
    def _hav(la1, lo1, la2, lo2):
        if None in (la1, lo1, la2, lo2):
            return 1e9
        r = 6371.0
        dlat = math.radians(la2 - la1)
        dlon = math.radians(lo2 - lo1)
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(la1)) * math.cos(math.radians(la2)) *
             math.sin(dlon / 2) ** 2)
        return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    rate_now = float(obj.get("lightning_count_10km", 0.0) or 0.0)
    rate_old = 0.0
    for cand in older or []:
        if _hav(float(lat), float(lon),
                cand.get("lat"), cand.get("lon")) <= 10.0:
            rate_old = float(cand.get("lightning_count_10km", 0.0) or 0.0)
            break

    if rate_old < 1.0:
        return 1.0 if rate_now < 1.0 else 3.0
    jump = rate_now / rate_old
    return round(min(max(jump, 0.1), 10.0), 2)


# ---------------------------------------------------------------------------
# hail_prob2 — SHIP-basierte Hagel-Wahrscheinlichkeit
# ---------------------------------------------------------------------------
def _compute_hail_prob2(obj: dict, ship: float, lapse: float,
                        shear_kmh: float, jump: float) -> float:
    """
    Aggregierte Hagel-Wahrscheinlichkeit auf Basis SHIP + Zusatzfeatures.
    Ergebnis 0.0-1.0, kompatibel mit HAIL_WARN_THRESHOLD.

    Gewichtung (Heuristik, durch ML kalibrierbar):
      - SHIP in (0, 3]      : 40 %
      - Lapse 5-9 Grad/km  : 20 %
      - Shear 10-25 m/s    : 20 %
      - Lightning Jump > 2 : 10 %
      - Core-Ratio          : 10 %
    """
    def _norm(v, lo, hi):
        if hi <= lo:
            return 0.0
        return max(0.0, min(1.0, (v - lo) / (hi - lo)))

    core_ratio = float(obj.get("core_ratio", 0.0) or 0.0)
    fl_h       = float(obj.get("arome_fl_height", 4000.0) or 4000.0)
    shear_ms   = shear_kmh / 3.6

    score = (
        0.40 * _norm(ship,       0.0,  3.0) +
        0.20 * _norm(lapse,      5.0,  9.0) +
        0.20 * _norm(shear_ms,  10.0, 25.0) +
        0.10 * (1.0 if jump > 2.0 else 0.0) +
        0.10 * _norm(core_ratio, 0.3,  1.0)
    )

    # Gefriergrenze daempfen: ueber 4500 m kein Boden-Hagel mehr
    if fl_h > 4500.0:
        score *= max(0.0, (5500.0 - fl_h) / 1000.0)

    return round(max(0.0, min(1.0, score)), 3)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def assign_convective_indices(objects: list, timestamp: str | None = None) -> list:
    """
    Berechnet konvektive Indizes fuer alle Objekte aus bereits vorhandenen Feldern.
    Kein Netzwerk-Aufruf. Sicher bei leerer Liste oder fehlenden Feldern.

    Parameter
    ---------
    objects   : Liste der Sturmzellen-Objekte mit bereits gesetzten Wetterfeldern.
    timestamp : Optional, nur fuer Logging.

    Rueckgabe
    ---------
    Dieselbe Liste, in-place erweitert um die neuen Felder.
    """
    if not objects:
        debug_log("[CONV-IDX] Keine Objekte — Skip.")
        return objects

    now = datetime.utcnow()
    n_ok = 0
    for o in objects:
        if o.get("lat") is None or o.get("lon") is None:
            # Defaults setzen, damit ML-Pipeline keine fehlenden Keys hat
            o.setdefault("lapse_700_500", 0.0)
            o.setdefault("shear_0_6km_speed", 0.0)
            o.setdefault("shear_0_6km_dir_cos", 0.0)
            o.setdefault("shear_0_6km_dir_sin", 0.0)
            o.setdefault("mixr", 0.0)
            o.setdefault("ship_index", 0.0)
            o.setdefault("lightning_jump", 1.0)
            o.setdefault("hail_prob2", 0.0)
            continue

        # 1) Lapse Rate 700-500
        lapse = _compute_lapse_700_500(o)

        # 2) 0-6-km-Scherung
        shear_kmh, sh_cos, sh_sin = _compute_shear_0_6km(o)

        # 3) Mischungsverhaeltnis aus Td
        td = float(o.get("arome_td2m", 0.0) or 0.0)
        mixr = _mixing_ratio_g_kg(td)

        # 4) SHIP
        ship = _compute_ship(o, lapse, shear_kmh, mixr)

        # 5) Lightning Jump
        jump = _compute_lightning_jump(o, now=now)

        # 6) Aggregierte Hagelwahrscheinlichkeit 2
        hp2 = _compute_hail_prob2(o, ship, lapse, shear_kmh, jump)

        o["lapse_700_500"]      = lapse
        o["shear_0_6km_speed"]  = shear_kmh
        o["shear_0_6km_dir_cos"] = sh_cos
        o["shear_0_6km_dir_sin"] = sh_sin
        o["mixr"]               = round(mixr, 2)
        o["ship_index"]         = ship
        o["lightning_jump"]     = jump
        o["hail_prob2"]         = hp2
        n_ok += 1

    debug_log(f"[CONV-IDX] {n_ok}/{len(objects)} Objekte mit konvektiven Indizes versorgt.")
    return objects
