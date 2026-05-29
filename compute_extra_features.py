# compute_extra_features.py
"""
Rein rechnerische Erweiterungs-Features fuer das ML (KEIN neuer API-Call).

Laeuft in der Live-Pipeline NACH compute_convective_indices.assign_convective_indices(),
liest also bereits angereicherte Objektfelder (arome_*, t500_c, t700_c, lapse_700_500,
wind_speed_700hPa/850hPa + Richtungen, cape, arome_li, area, core_ratio, vx, vy).

Alle Werte sind physikalisch motivierte APPROXIMATIONEN, klar als Proxy gekennzeichnet.
Fehlt eine Eingangsgroesse, wird das jeweilige Feature 0.0 gesetzt (Modell lernt das
als 'fehlend').
"""

import math
import time

try:
    from debug_utils import debug_log
except Exception:
    def debug_log(msg):
        print(msg)

# In-Memory-Ringpuffer fuer Zelltrends (Prozess-lokal, lebt im Live-Loop von main.py).
# Struktur: { cell_id: [(epoch_s, cape, li), ...] }  — gekappt auf TREND_WINDOW_S.
_TREND_CACHE: dict = {}
TREND_WINDOW_S = 40 * 60      # 40 min Fenster
TREND_TARGET_S = 30 * 60      # Trend bezieht sich auf ~30 min zurueck
AREA_NORM      = 4000.0       # Normierung fuer vil_proxy (px-Flaeche; rein relativ)


def _f(v, default=0.0):
    try:
        out = float(v)
        if math.isnan(out) or math.isinf(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def _wind_vector_kmh(speed_kmh, dir_deg):
    """Meteorologische Windrichtung (woher) -> kartesischer (u,v)-Vektor (wohin)."""
    s = _f(speed_kmh)
    d = _f(dir_deg)
    rad = math.radians(d)
    # Wind weht VON dir -> Bewegungsvektor zeigt in (dir+180).
    u = -s * math.sin(rad)
    v = -s * math.cos(rad)
    return u, v


def _dir_from_cos_sin(cos_v, sin_v):
    """Rekonstruiert Grad aus cos/sin-codierter Richtung."""
    return (math.degrees(math.atan2(_f(sin_v), _f(cos_v)))) % 360.0


def _compute_dcape(obj):
    """Downdraft-CAPE-Proxy: trockene Mittelschicht + steile Lapse-Rate -> starke Abwinde."""
    t2m  = _f(obj.get("arome_t2m"))
    td2m = _f(obj.get("arome_td2m"))
    lapse = _f(obj.get("lapse_700_500"))
    if t2m == 0.0 and td2m == 0.0:
        return 0.0
    depression = max(0.0, t2m - td2m)                 # K
    f_dry   = min(depression / 20.0, 1.0)             # 0..1
    f_lapse = min(max(lapse, 0.0) / 8.0, 1.5)         # 0..1.5
    return round(1000.0 * f_dry * f_lapse, 1)         # J/kg (Proxy)


def _compute_low_level_shear(obj):
    """0-1 km (850 hPa) und 0-3 km (700 hPa) Scherung als Vektordifferenz zum 10-m-Wind."""
    u10, v10 = _wind_vector_kmh(obj.get("arome_ff10m"),
                                _dir_from_cos_sin(obj.get("arome_dd_cos"), obj.get("arome_dd_sin")))
    # 850 hPa wird in fetch_700hpa_wind nicht zwingend gefuellt -> Fallback ueber 700 hPa.
    s850 = _f(obj.get("wind_speed_850hPa"))
    d850 = _dir_from_cos_sin(obj.get("wind_dir_850_cos"), obj.get("wind_dir_850_sin"))
    u850, v850 = _wind_vector_kmh(s850, d850) if s850 > 0 else (u10, v10)

    s700 = _f(obj.get("wind_speed_700hPa"))
    d700 = _dir_from_cos_sin(obj.get("wind_dir_cos"), obj.get("wind_dir_sin"))
    u700, v700 = _wind_vector_kmh(s700, d700) if s700 > 0 else (u850, v850)

    shear01 = math.hypot(u850 - u10, v850 - v10)
    shear03 = math.hypot(u700 - u10, v700 - v10)
    return round(shear01, 1), round(shear03, 1), (u700 - u10, v700 - v10)


def _compute_srh(obj, shear03_vec):
    """SRH-0-3-km-Proxy: Betrag der zur Zellbewegung senkrechten (streamwise) Scherung."""
    vx = _f(obj.get("vx"))
    vy = _f(obj.get("vy"))
    if vx == 0.0 and vy == 0.0:
        return 0.0
    su, sv = shear03_vec
    motion = math.hypot(vx, vy)
    if motion < 1e-6:
        return 0.0
    # Kreuzprodukt-Betrag (Scherung x Bewegungsrichtung) ~ streamwise vorticity Proxy.
    cross = abs(su * vy - sv * vx) / motion
    return round(cross * motion, 1)   # m^2/s^2 (Proxy, dimensionsanalog)


def _compute_trends(obj):
    """ΔCAPE / ΔLI ueber ~30 min aus dem Prozess-lokalen Ringpuffer."""
    cid = str(obj.get("id", ""))
    now = time.time()
    cape = _f(obj.get("cape"))
    li   = _f(obj.get("arome_li"))
    buf = _TREND_CACHE.setdefault(cid, [])
    buf.append((now, cape, li))
    # Fenster kappen
    _TREND_CACHE[cid] = [e for e in buf if now - e[0] <= TREND_WINDOW_S]
    buf = _TREND_CACHE[cid]
    # naechsten Eintrag ~30 min zurueck suchen
    ref = None
    for e in buf:
        if now - e[0] >= TREND_TARGET_S * 0.6:   # >= ~18 min gilt als Referenz
            ref = e
            break
    if ref is None:
        return 0.0, 0.0
    return round(cape - ref[1], 1), round(li - ref[2], 2)


def _compute_vil_proxy(obj):
    core = min(max(_f(obj.get("core_ratio")), 0.0), 1.0)
    area = _f(obj.get("area"))
    return round(core * min(area / AREA_NORM, 3.0), 4)


def assign_extra_features(objects):
    """
    Reichert jede erkannte Zelle um die 7 Erweiterungs-Features an.
    Erwartet eine Liste von Objekt-Dicts (in-place Anreicherung). Gibt die Liste zurueck.
    """
    if not objects:
        return objects
    enriched = 0
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        try:
            obj["dcape"] = _compute_dcape(obj)
            s01, s03, s03vec = _compute_low_level_shear(obj)
            obj["shear_0_1km_speed"] = s01
            obj["shear_0_3km_speed"] = s03
            obj["srh_0_3km"] = _compute_srh(obj, s03vec)
            ct, lt = _compute_trends(obj)
            obj["cape_trend_30min"] = ct
            obj["li_trend_30min"] = lt
            obj["vil_proxy"] = _compute_vil_proxy(obj)
            enriched += 1
        except Exception as exc:
            debug_log(f"[EXTRA-FEATURES] Fehler bei Zelle {obj.get('id')}: {exc}")
            for k in ("dcape", "shear_0_1km_speed", "shear_0_3km_speed",
                      "srh_0_3km", "cape_trend_30min", "li_trend_30min", "vil_proxy"):
                obj.setdefault(k, 0.0)
    debug_log(f"[EXTRA-FEATURES] {enriched} Zellen angereichert")
    return objects
