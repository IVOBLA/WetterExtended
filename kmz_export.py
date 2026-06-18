# kmz_export.py
"""
KMZ-Export der aktuellen Zelllandschaft und Vorhersage-Layer.

Layer im erzeugten KMZ:
  1. „Aktuelle Zellen"        — Polygon-Konturen + Mittelpunkt-Marker
  2. „Vorhersage +Hmin"       — je Forecast-Horizont: Punkt + Pfeil
  3. „Unsicherheit +Hmin"     — q10/q90-Ellipsen (falls vorhanden)
  4. „Betroffene Orte"        — Locations mit Hit, in Forecast-Farbe

Fix P08:
  - Aktuelle Zellen + Konturen + Location-Hits werden mit exportiert
    (Zieldefinition §11/§16/§25).
  - Farb-Lookup toleriert int- und str-Keys (runtime_overrides.json
    speichert Dict-Keys als Strings).
  - Stilinformationen (Linienstärke / Strichmuster) aus
    FORECAST_ARROW_STYLE werden respektiert.
"""

import math

import simplekml

from geo_utils import pixel_to_geo

try:
    from debug_utils import debug_log
except Exception:
    def debug_log(msg):
        print(msg)


CELL_POLYGON_COLOR = "#0b1f5e"


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


def _resolve_horizon_value(d: dict, horizon, default):
    """Liefert d[horizon] für int- ODER str-Keys (JSON-Roundtrip-tolerant)."""
    if d is None:
        return default
    if horizon in d:
        return d[horizon]
    sh = str(horizon)
    if sh in d:
        return d[sh]
    return default


def save_forecast_as_kmz(
    forecasts_by_horizon: dict,
    colors_by_horizon: dict,
    output_path: str = "forecast.kmz",
    current_objects: list | None = None,
    location_hits: list | None = None,
    style_by_horizon: dict | None = None,
    ir_tracks: list | None = None,
) -> str:
    """
    Schreibt ein KMZ mit allen geforderten Layern.

    Parameter
    ---------
    forecasts_by_horizon : {h: [forecast_obj, ...]}
        Forecast-Objekte (aus prediction.predict_positions) mit
        x, y, lat, lon, origin_lat, origin_lon, optional x_q10/x_q90.
    colors_by_horizon    : {h: "#RRGGBB"}
        Vorhersagepfeil-Farben pro Horizont (Admin-Panel).
    output_path          : Pfad zum geschriebenen .kmz.
    current_objects      : Liste aktueller Zellobjekte aus object_tracking.
                           Genutzt für „Aktuelle Zellen"-Layer.
    location_hits        : Liste von Locations mit Hits aus
                           locations_check.annotate_locations().
    style_by_horizon     : Optional. {h: {"weight": int, "dash": str}}.
                           Wenn None, wird Default-Linienstärke verwendet.

    Rückgabe: output_path
    """
    kml = simplekml.Kml()

    # ── Layer 1: Aktuelle Zellen ───────────────────────────────────────────
    if current_objects:
        current_folder = kml.newfolder(name="Aktuelle Zellen")
        for obj in current_objects:
            try:
                lat = float(obj.get("lat"))
                lon = float(obj.get("lon"))
            except (TypeError, ValueError):
                continue
            tech_id = obj.get("id", "cell")
            cell_id = obj.get("cell_id") or tech_id
            # Mittelpunkt
            pnt = current_folder.newpoint(name=str(tech_id), coords=[(lon, lat)])
            pnt.description = f"Technische ID: {tech_id}\nCell-ID: {cell_id}"
            try:
                pnt.extendeddata.newdata(name="id", value=str(tech_id))
                pnt.extendeddata.newdata(name="cell_id", value=str(cell_id))
            except Exception:
                pass
            pnt.style.iconstyle.icon.href = (
                "http://maps.google.com/mapfiles/kml/shapes/triangle.png"
            )
            pnt.style.iconstyle.scale = 0.7
            pnt.style.iconstyle.color = _hex_to_kml_color(CELL_POLYGON_COLOR)

            # Kontur (in SKALIERTEN Pixeln gespeichert).
            contour = obj.get("contour")
            if isinstance(contour, list) and len(contour) >= 3:
                try:
                    poly_coords = []
                    for pt in contour:
                        # cv2-Kontur-Format: [[[x,y]]] oder [[x,y]]
                        if isinstance(pt, list) and pt and isinstance(pt[0], list):
                            x_px, y_px = float(pt[0][0]), float(pt[0][1])
                        elif isinstance(pt, list) and len(pt) >= 2:
                            x_px, y_px = float(pt[0]), float(pt[1])
                        else:
                            continue
                        plat, plon = pixel_to_geo(x_px, y_px)
                        poly_coords.append((plon, plat))
                    if len(poly_coords) >= 3:
                        # Polygon schließen
                        if poly_coords[0] != poly_coords[-1]:
                            poly_coords.append(poly_coords[0])
                        poly = current_folder.newpolygon(
                            name=f"{cell_id}_contour",
                            outerboundaryis=poly_coords,
                        )
                        poly.style.polystyle.color = _hex_to_kml_color(CELL_POLYGON_COLOR, alpha=60)
                        poly.style.polystyle.fill = 1
                        poly.style.linestyle.color = _hex_to_kml_color(CELL_POLYGON_COLOR)
                        poly.style.linestyle.width = 2
                except Exception as _exc:
                    debug_log(f"[KMZ] Kontur-Export für {cell_id} übersprungen: {_exc}")

    # ── Layer 2/3: Forecast-Pfeile + Unsicherheits-Ellipsen ────────────────
    for horizon, forecast_list in (forecasts_by_horizon or {}).items():
        hex_color = _resolve_horizon_value(colors_by_horizon, horizon, "#888888")
        style = _resolve_horizon_value(style_by_horizon, horizon, {})
        weight = int(style.get("weight", max(2, int(int(horizon) // 20)))) if style else max(2, int(int(horizon) // 20))
        dash = style.get("dash", "") if style else ""
        color_kml = _hex_to_kml_color(hex_color)

        folder = kml.newfolder(name=f"Forecast +{horizon}min")
        for obj in forecast_list or []:
            try:
                lat, lon = pixel_to_geo(obj["x"], obj["y"])
            except Exception:
                continue

            tech_id = obj.get("id", "forecast")
            cell_id = obj.get("cell_id") or tech_id
            pnt = folder.newpoint(name=f"{tech_id}_+{horizon}m", coords=[(lon, lat)])
            pnt.description = f"Technische ID: {tech_id}\nCell-ID: {cell_id}"
            try:
                pnt.extendeddata.newdata(name="id", value=str(tech_id))
                pnt.extendeddata.newdata(name="cell_id", value=str(cell_id))
            except Exception:
                pass
            pnt.style.iconstyle.icon.href = (
                "http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png"
            )
            pnt.style.iconstyle.scale = 0.5
            pnt.style.iconstyle.color = color_kml

            origin_lat = obj.get("origin_lat")
            origin_lon = obj.get("origin_lon")
            if origin_lat is not None and origin_lon is not None:
                line = folder.newlinestring(
                    name=f"{cell_id}_arrow_+{horizon}m",
                    coords=[(origin_lon, origin_lat), (lon, lat)],
                )
                line.style.linestyle.color = color_kml
                line.style.linestyle.width = weight

            if all(k in obj for k in ("x_q10", "x_q90", "y_q10", "y_q90")):
                cx = (float(obj["x_q10"]) + float(obj["x_q90"])) / 2.0
                cy = (float(obj["y_q10"]) + float(obj["y_q90"])) / 2.0
                rx = max(abs(float(obj["x_q90"]) - float(obj["x_q10"])) / 2.0, 1.0)
                ry = max(abs(float(obj["y_q90"]) - float(obj["y_q10"])) / 2.0, 1.0)
                poly = folder.newpolygon(
                    name=f"{cell_id}_uncertainty_+{horizon}m",
                    outerboundaryis=_ellipse_coords(cx, cy, rx, ry),
                )
                poly.style.polystyle.color = _hex_to_kml_color(hex_color, alpha=80)
                poly.style.polystyle.fill = 1
                poly.style.polystyle.outline = 0

    # ── Layer 4: Betroffene Orte ──────────────────────────────────────────
    if location_hits:
        loc_folder = kml.newfolder(name="Betroffene Orte")
        for loc in location_hits:
            try:
                lat = float(loc["lat"])
                lon = float(loc["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            name = str(loc.get("name", "Ort"))
            hits = loc.get("hits") or {}
            if not hits:
                continue
            if 0 in hits or "0" in hits:
                primary = hits.get(0) or hits.get("0")
            else:
                sorted_keys = sorted(
                    hits.keys(),
                    key=lambda k: int(k) if str(k).isdigit() else 99999,
                )
                primary = hits.get(sorted_keys[0]) if sorted_keys else None
            if not primary:
                continue
            color = primary.get("color", "#dc2626")
            hit_type = primary.get("hit_type", "current")
            pnt = loc_folder.newpoint(
                name=f"{name} ({hit_type})",
                coords=[(lon, lat)],
            )
            pnt.style.iconstyle.icon.href = (
                "http://maps.google.com/mapfiles/kml/shapes/target.png"
            )
            pnt.style.iconstyle.scale = 1.2
            pnt.style.iconstyle.color = _hex_to_kml_color(color)
            pnt.description = (
                f"Treffertyp: {hit_type}\n"
                f"Zellen-ID: {primary.get('cell_id', '?')}\n"
                f"Distanz: {primary.get('distance_km', '?')} km\n"
                f"Geschwindigkeit: {primary.get('speed_kmh', '?')} km/h"
            )

    # ── Phase E: IR-Vorläuferzellen Layer ─────────────────────────────────────
    if ir_tracks:
        ir_folder = kml.newfolder(name="IR-Cells (Vorläufer)")
        for ir in ir_tracks:
            try:
                ir_lat = float(ir.get("lat", 0))
                ir_lon = float(ir.get("lon", 0))
                ir_id  = ir.get("ir_id", "ir_?")
                bt_min = ir.get("bt_min_k", 0.0)
                age    = ir.get("cloud_age_min", 0.0)
                ot     = ir.get("overshooting_top", 0.0)
                trend  = ir.get("bt_trend_k_per_min", 0.0)

                # Marker
                pnt = ir_folder.newpoint(
                    name=f"{ir_id} ({bt_min:.0f}K)",
                    coords=[(ir_lon, ir_lat)],
                    description=(
                        f"IR-Vorläufer | BT_min={bt_min:.1f}K | "
                        f"Trend={trend:+.2f}K/min | Age={age:.0f}min | "
                        f"OT={'ja' if ot else 'nein'}"
                    )
                )
                # Violettes Icon für IR-Cells
                pnt.style.iconstyle.icon.href = (
                    "http://maps.google.com/mapfiles/kml/paddle/purple-circle.png"
                )
                pnt.style.iconstyle.scale = 0.8
                pnt.style.iconstyle.color = "ffff00ff"  # KML: AABBGGRR → Violett

                # Bewegungspfeil (gestrichelt, wenn Geschwindigkeit > 0)
                vx = float(ir.get("vx_deg_min", 0.0))
                vy = float(ir.get("vy_deg_min", 0.0))
                if abs(vx) > 0.0001 or abs(vy) > 0.0001:
                    # 30-min-Vorhersageposition
                    fc_lat = ir_lat + vy * 30.0
                    fc_lon = ir_lon + vx * 30.0
                    arrow = ir_folder.newlinestring(
                        name=f"{ir_id}_arrow_30min",
                        coords=[(ir_lon, ir_lat), (fc_lon, fc_lat)],
                    )
                    arrow.style.linestyle.color = "ffff00ff"  # Violett KML
                    arrow.style.linestyle.width = 2
            except Exception as _ir_kml_exc:
                debug_log(f"[KMZ] IR-Cell {ir.get('ir_id','?')} fehlgeschlagen: {_ir_kml_exc}")

    kml.savekmz(output_path)
    debug_log(f"Vorhersage als KMZ gespeichert: {output_path}")
    return output_path
