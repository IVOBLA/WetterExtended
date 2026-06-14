"""B127: Treffer wenn der vorhergesagte Zellrand den Radius ZWISCHEN Horizonten streift."""
import locations_check as lc


def _square_contour(center_lat, center_lon, half_deg):
    """Quadratisches Geo-Polygon [[lon,lat],...] um (center)."""
    return [
        [center_lon - half_deg, center_lat - half_deg],
        [center_lon + half_deg, center_lat - half_deg],
        [center_lon + half_deg, center_lat + half_deg],
        [center_lon - half_deg, center_lat + half_deg],
        [center_lon - half_deg, center_lat - half_deg],
    ]


def test_grazing_segment_detects_edge_between_horizons():
    """Mittelpunkt zieht in ~6 km Abstand vorbei; der Zellrand streift jedoch
    bei einem Sub-Schritt den 2-km-Radius → Helfer muss True liefern."""
    loc_lat, loc_lon, radius = 46.72, 14.10, 2.0
    half = 0.05  # ~5–6 km halbe Kantenlänge → breite Zelle
    obj = {
        "lat": 46.78, "lon": 14.10,
        "contour_geo": _square_contour(46.78, 14.10, half),
        "history": [{"timestamp": "2026-06-14_18-15-00",
                     "lat_span_km": 11.0, "lon_span_km": 11.0}],
    }
    # Zentrum zieht von Norden (m0) nach Süden (m1), bleibt ~6 km westlich/nördlich,
    # der breite Südrand überstreicht dabei den Ortsradius.
    hit = lc._forecast_contour_grazes_segment(
        obj, loc_lat, loc_lon, radius,
        46.80, 14.10, 20.0,   # c0 @ +20 min
        46.74, 14.10, 30.0,   # c1 @ +30 min
        step_min=2.0,
    )
    assert hit is True


def test_no_graze_when_far_away():
    """Zelle zieht klar östlich vorbei (lon 14.40) → kein Treffer am 2-km-Ort (lon 14.10)."""
    loc_lat, loc_lon, radius = 46.72, 14.10, 2.0
    obj = {
        "lat": 46.73, "lon": 14.40,
        "contour_geo": _square_contour(46.73, 14.40, 0.03),
        "history": [{"timestamp": "2026-06-14_18-15-00",
                     "lat_span_km": 6.0, "lon_span_km": 6.0}],
    }
    hit = lc._forecast_contour_grazes_segment(
        obj, loc_lat, loc_lon, radius,
        46.73, 14.40, 20.0,
        46.70, 14.47, 30.0,
        step_min=2.0,
    )
    assert hit is False


def test_radius_independent_small_vs_large():
    """Bei großem Radius trifft dieselbe Bahn, bei winzigem nicht — Radiusabhängigkeit
    ausschließlich über die Geometrie, kein Sonderfall für kleine Radien."""
    loc_lat, loc_lon = 46.72, 14.10
    obj = {
        "lat": 46.78, "lon": 14.20,
        "contour_geo": _square_contour(46.78, 14.20, 0.02),
        "history": [{"timestamp": "2026-06-14_18-15-00",
                     "lat_span_km": 4.0, "lon_span_km": 4.0}],
    }
    big = lc._forecast_contour_grazes_segment(
        obj, loc_lat, loc_lon, 15.0,
        46.80, 14.20, 20.0, 46.74, 14.18, 30.0, step_min=2.0,
    )
    tiny = lc._forecast_contour_grazes_segment(
        obj, loc_lat, loc_lon, 0.2,
        46.80, 14.20, 20.0, 46.74, 14.18, 30.0, step_min=2.0,
    )
    assert big is True
    assert tiny is False
