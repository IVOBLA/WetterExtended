# kmz_export.py

import os
import simplekml
import math
import debug_utils
from ftplib import FTP
from geo_utils import pixel_to_geo
from debug_utils import debug_log

def save_forecast_as_kmz(forecast_10, forecast_20, forecast_30):
    kml = simplekml.Kml()

    for label, forecast in zip(["10min", "20min", "30min"], [forecast_10, forecast_20, forecast_30]):
        for obj in forecast:
            lat, lon = pixel_to_geo(obj["x"], obj["y"])
            pnt = kml.newpoint(name = obj.get("id", "forecast"), coords=[(lon, lat)])
            pnt.style.iconstyle.icon.href = "http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png"
            pnt.style.iconstyle.scale = 0.5
            if all(key in obj for key in ["x_q10", "x_q90", "y_q10", "y_q90"]):
                cx = (float(obj["x_q10"]) + float(obj["x_q90"])) / 2.0
                cy = (float(obj["y_q10"]) + float(obj["y_q90"])) / 2.0
                rx = max(abs(float(obj["x_q90"]) - float(obj["x_q10"])) / 2.0, 1.0)
                ry = max(abs(float(obj["y_q90"]) - float(obj["y_q10"])) / 2.0, 1.0)
                coords = []
                for deg in range(0, 361, 15):
                    angle = math.radians(deg)
                    x = cx + rx * math.cos(angle)
                    y = cy + ry * math.sin(angle)
                    e_lat, e_lon = pixel_to_geo(x, y)
                    coords.append((e_lon, e_lat))
                poly = kml.newpolygon(
                    name=f"{obj.get('id', 'forecast')}_{label}_uncertainty",
                    outerboundaryis=coords,
                )
                poly.style.polystyle.color = "7f00ffff"
                poly.style.polystyle.fill = 1
                poly.style.polystyle.outline = 0

    kml_path = "forecast.kmz"
    kml.savekmz(kml_path)
    debug_log(f"Vorhersage als KMZ gespeichert: {kml_path}")
