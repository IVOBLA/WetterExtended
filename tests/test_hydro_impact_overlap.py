import hydro_impact


def _poly(w, s, e, n):
    return {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}


def test_overlap_requires_real_catchment_intersection():
    cell = {"id": 42, "contour_geo": [[13.0, 46.0], [13.1, 46.0], [13.1, 46.1], [13.0, 46.1], [13.0, 46.0]]}
    miss = {"type": "Feature", "properties": {"station_id": "123"}, "geometry": _poly(14.0, 47.0, 14.1, 47.1)}

    overlap = hydro_impact.compute_cell_catchment_overlap(cell, miss)

    assert overlap["hit"] is False
    assert overlap["overlap_area_km2"] == 0.0


def test_overlap_reports_area_and_ratios_for_catchment_hit():
    cell = {"id": 42, "contour_geo": [[13.0, 46.0], [13.2, 46.0], [13.2, 46.2], [13.0, 46.2], [13.0, 46.0]]}
    catchment = {"type": "Feature", "properties": {"station_id": "123"}, "geometry": _poly(13.1, 46.0, 13.3, 46.2)}

    overlap = hydro_impact.compute_cell_catchment_overlap(cell, catchment)

    assert overlap["hit"] is True
    assert overlap["overlap_area_km2"] > 0
    assert 0.45 <= overlap["overlap_ratio_cell"] <= 0.55
    assert 0.45 <= overlap["overlap_ratio_catchment"] <= 0.55
