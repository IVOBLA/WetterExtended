# weather_api.py
"""
TAWES-Wetterdaten für WetterExtended.

Diese Datei ist ein dünner Adapter. Der eigentliche HTTP-Request und die
Caching-Logik liegen in fetch_tawes_gust.fetch_tawes_stations().
Alle Stationen werden über den zentralen Cache mit 10-min-TTL geliefert.
"""

from debug_utils import debug_log


def get_weather_data(include_all_stations: bool = True) -> list:
    """
    Gibt Wetterdaten aller Kärntner TAWES-Stationen zurück.
    Delegiert vollständig an fetch_tawes_stations() — kein eigener HTTP-Request.

    Rückgabe: Liste von Station-Dicts mit Feldern:
      station_id, name, lat, lon,
      TL, TP, FF, FFX, RR, DD, P, RF, GLOW  (SI-Einheiten)
      ffx_kmh, ff_kmh, rr_mm, tl_c          (abgeleitete Felder)
    """
    from fetch_tawes_gust import fetch_tawes_stations

    stations = fetch_tawes_stations()
    if stations:
        debug_log(f"[weather_api] {len(stations)} Stationen via fetch_tawes_stations()")
    else:
        debug_log("[weather_api] Keine Stationsdaten verfügbar (fetch_tawes_stations gab [] zurück)")
    return stations
