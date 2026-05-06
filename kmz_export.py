import math
import simplekml
from geo_utils import pixel_to_geo

try:
    from debug_utils import debug_log
except Exception:
    def debug_log(msg):
        print(msg)


def _hex_to_kml_color(hex_color: str, alpha: int = 255) -> str:
    h = (hex_color or "#888888").lstrip("#")
    if len(h) != 6:
        h = "888888"
    r, g, b = h[0:2], h[2:4], h[4:6]
    a = f"{max(0, min(255, alpha)):02x}"
    return f"{a}{b}{g}{r}"


def _ellipse_coords(cx, cy, rx, ry, steps=24):
    coords = []
    for i in range(steps + 1):
        ang = 2 * math.pi * (i / steps)
        x = cx + rx * math.cos(ang)
        y = cy + ry * math.sin(ang)
        e_lat, e_lon = pixel_to_geo(x, y)
        coords.append((e_lon, e_lat))
    return coords


def save_forecast_as_kmz(forecasts_by_horizon: dict, colors_by_horizon: dict, output_path: str = "forecast.kmz") -> str:
    """forecasts_by_horizon: {h: [obj, ...]} mit obj enthaltend x, y, x_q10/y_q10/...
    colors_by_horizon: {h: '#rrggbb'}
    """
    kml = simplekml.Kml()

    for horizon, forecast_list in (forecasts_by_horizon or {}).items():
        color_kml = _hex_to_kml_color(colors_by_horizon.get(horizon, "#888888"))
        folder = kml.newfolder(name=f"Forecast +{horizon}min")

        for obj in forecast_list or []:
            try:
                lat, lon = pixel_to_geo(obj["x"], obj["y"])
            except Exception:
                continue

            cell_id = obj.get("id", "forecast")

            pnt = folder.newpoint(name=f"{cell_id}_+{horizon}m", coords=[(lon, lat)])
            pnt.style.iconstyle.icon.href = "http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png"
            pnt.style.iconstyle.scale = 0.5
            pnt.style.iconstyle.color = color_kml

            origin_lat, origin_lon = obj.get("origin_lat"), obj.get("origin_lon")
            if origin_lat is not None and origin_lon is not None:
                line = folder.newlinestring(
                    name=f"{cell_id}_arrow_+{horizon}m",
                    coords=[(origin_lon, origin_lat), (lon, lat)],
                )
                line.style.linestyle.color = color_kml
                line.style.linestyle.width = max(2, int(horizon // 20))

            if all(k in obj for k in ("x_q10", "x_q90", "y_q10", "y_q90")):
                cx = (float(obj["x_q10"]) + float(obj["x_q90"])) / 2.0
                cy = (float(obj["y_q10"]) + float(obj["y_q90"])) / 2.0
                rx = max(abs(float(obj["x_q90"]) - float(obj["x_q10"])) / 2.0, 1.0)
                ry = max(abs(float(obj["y_q90"]) - float(obj["y_q10"])) / 2.0, 1.0)
                poly = folder.newpolygon(
                    name=f"{cell_id}_uncertainty_+{horizon}m",
                    outerboundaryis=_ellipse_coords(cx, cy, rx, ry),
                )
                poly.style.polystyle.color = _hex_to_kml_color(colors_by_horizon.get(horizon, "#888888"), alpha=80)
                poly.style.polystyle.fill = 1
                poly.style.polystyle.outline = 0

    kml.savekmz(output_path)
    debug_log(f"Vorhersage als KMZ gespeichert: {output_path}")
    return output_path
