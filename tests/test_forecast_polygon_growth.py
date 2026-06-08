"""B59/P-T04: Verifiziert, dass Größenwachstum das Forecast-Polygon vergrößert."""
import pytest


def _poly_bbox_span(poly):
    """Max N-S- und E-W-Ausdehnung eines [[lon,lat],...]-Polygons (grob, in Grad)."""
    lons = [p[0] for p in poly]
    lats = [p[1] for p in poly]
    return (max(lats) - min(lats), max(lons) - min(lons))


def _base_obj(spans):
    """Baut ein Objekt mit History aus (timestamp, lat_span_km, lon_span_km)."""
    history = [
        {"timestamp": ts, "lat_span_km": ns, "lon_span_km": ew}
        for ts, ns, ew in spans
    ]
    # Quadrat-Kontur um (14.30, 46.62), ~0.1° Kante
    contour = [
        [14.25, 46.57], [14.35, 46.57],
        [14.35, 46.67], [14.25, 46.67], [14.25, 46.57],
    ]
    return {
        "id": "t1", "lat": 46.62, "lon": 14.30,
        "contour_geo": contour, "history": history,
    }


def test_growing_cell_polygon_larger_than_stable():
    try:
        from locations_check import _forecast_polygon_at_h
    except ImportError as exc:
        pytest.skip(f"locations_check nicht importierbar: {exc}")

    # Stabil: konstante Spans
    stable = _base_obj([
        ("2025-06-01_12-00-00", 10.0, 10.0),
        ("2025-06-01_12-05-00", 10.0, 10.0),
        ("2025-06-01_12-10-00", 10.0, 10.0),
    ])
    # Wachsend: Spans nehmen deutlich zu
    growing = _base_obj([
        ("2025-06-01_12-00-00", 10.0, 10.0),
        ("2025-06-01_12-05-00", 13.0, 13.0),
        ("2025-06-01_12-10-00", 16.0, 16.0),
    ])

    h = 30.0  # Minuten
    fl, fn = 46.70, 14.40  # gleiche Forecast-Position für beide

    p_stable = _forecast_polygon_at_h(stable, fl, fn, h)
    p_growing = _forecast_polygon_at_h(growing, fl, fn, h)

    assert len(p_stable) >= 3 and len(p_growing) >= 3

    ns_s, ew_s = _poly_bbox_span(p_stable)
    ns_g, ew_g = _poly_bbox_span(p_growing)

    # Wachsende Zelle muss ein (deutlich) größeres Polygon liefern
    assert ns_g > ns_s, f"N-S: wachsend {ns_g} !> stabil {ns_s}"
    assert ew_g > ew_s, f"E-W: wachsend {ew_g} !> stabil {ew_s}"
