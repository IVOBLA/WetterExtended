# weather_api.py

import os
import requests
import json
import debug_utils
from datetime import datetime
from debug_utils import debug_log

def get_weather_data(include_all_stations=True):
    url = (
        "https://dataset.api.hub.geosphere.at/v1/station/current/tawes-v1-10min"
        "?parameters=RR,DD,FF,FFX,GLOW,P,RF,TL,TP"
        "&station_ids=11275,11218,11234,11206,11227,11235,11222,11273,"
        "11232,11259,11216,11349,11086,11255,11331,8989078,11217,11260,"
        "11215,11262,11278,11272,11229,11237,11213,11265,11257,11225,"
        "11228,8989076,11214"
        "&output_format=geojson"
    )

    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        params = ["RR", "DD", "FF", "FFX", "GLOW", "P", "RF", "TL", "TP"]

        stations = []
        for feature in data.get("features", []):
            props = feature.get("properties", {})
            geometry = feature.get("geometry", {})
            station_id = props.get("station", "unknown")
            name = props.get("name", f"Station {station_id}")
            coords = geometry.get("coordinates", [None, None])
            lon, lat = coords[0], coords[1]

            if lat is None or lon is None:
                debug_log(f"Station {station_id} hat keine Koordinaten — übersprungen")
                continue

            station = {
                "station_id": station_id,
                "name": name,
                "lon": lon,
                "lat": lat
            }

            for k in params:
                try:
                    val = props.get("parameters", {}).get(k, {}).get("data", [None])[0]
                    station[k] = float(val) if val is not None else 0
                except Exception:
                    station[k] = 0

            stations.append(station)

        if include_all_stations:
            debug_log(f"{len(stations)} Wetterstationen geladen")


        return stations

    except requests.exceptions.Timeout:
        from debug_utils import log_api_failure
        log_api_failure("GeoSphere-TAWES", url, "timeout", fallback_used=True)
        return []
    except requests.exceptions.HTTPError as e:
        from debug_utils import log_api_failure
        status = getattr(e.response, "status_code", None)
        log_api_failure("GeoSphere-TAWES", url, f"http-error: {e}",
                        fallback_used=True, http_status=status)
        return []
    except Exception as e:
        from debug_utils import log_api_failure
        log_api_failure("GeoSphere-TAWES", url, f"{type(e).__name__}: {e}",
                        fallback_used=True)
        return []
