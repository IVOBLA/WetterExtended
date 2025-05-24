# kmz_export.py

import os
import simplekml
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

    kml_path = "forecast.kmz"
    kml.savekmz(kml_path)
    debug_log(f"Vorhersage als KMZ gespeichert: {kml_path}")


