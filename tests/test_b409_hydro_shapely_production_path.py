import ast
import pytest

pytest.importorskip("shapely")

import hydro_flood_ml as h


def _station():
    return {"station_id": "S1", "q_m3s": 10.0, "mark_q_m3s": 20.0, "lat": 0.05, "lon": 0.05}


def _cell(cid="C1", coords=None, **extra):
    coords = coords or [[0.02, 0.02], [0.08, 0.02], [0.08, 0.08], [0.02, 0.08], [0.02, 0.02]]
    return {"id": cid, "contour_geo": coords, "lat": 0.05, "lon": 0.05, "nowcast_rain_rate_1h": 12.0, **extra}


def test_exactly_one_precip_from_cells_definition():
    tree = ast.parse(open("hydro_flood_ml.py", encoding="utf-8").read())
    defs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_precip_from_cells"]
    assert len(defs) == 1


def test_shapely_path_uses_real_polygon_not_bbox(monkeypatch):
    from shapely.geometry import Polygon
    catchment = Polygon([(0,0), (0.1,0), (0.1,0.03), (0.03,0.03), (0.03,0.1), (0,0.1), (0,0)])
    monkeypatch.setattr(h.runtime_config, "get", lambda name, default=None: 0.0 if name == "HYDRO_MIN_OVERLAP_AREA_KM2" else default)
    monkeypatch.setattr(h.__import__("hydro_impact"), "load_station_catchment_index", lambda force_reload=False: {"S1": {"station_id":"S1", "geometry": catchment, "feature_count":1, "status":"ok", "area_km2": 1, "signature":"x", "properties":{}}})
    monkeypatch.setattr(h.__import__("hydro_impact"), "catchment_diagnostics", lambda sid: {"catchment_geometry_available": True, "catchment_geometry_status":"ok", "catchment_feature_count":1, "catchment_area_geometry_km2": 1, "catchment_signature":"x"})
    row = h._precip_from_cells(_station(), [_cell()])
    assert row["catchment_geometry_available"] is True
    assert row["geometry_quality"] == "shapely"
    assert row["contributing_cell_count"] == 1
    assert row["physical_predicted_q_delta_m3s"] > 0


def test_l_shape_bbox_intersection_without_real_polygon_hit_is_ignored(monkeypatch):
    from shapely.geometry import Polygon
    catchment = Polygon([(0,0), (0.1,0), (0.1,0.03), (0.03,0.03), (0.03,0.1), (0,0.1), (0,0)])
    monkeypatch.setattr(h.runtime_config, "get", lambda name, default=None: 0.0 if name == "HYDRO_MIN_OVERLAP_AREA_KM2" else default)
    monkeypatch.setattr(h.__import__("hydro_impact"), "load_station_catchment_index", lambda force_reload=False: {"S1": {"station_id":"S1", "geometry": catchment, "feature_count":1, "status":"ok", "area_km2": 1, "signature":"x", "properties":{}}})
    monkeypatch.setattr(h.__import__("hydro_impact"), "catchment_diagnostics", lambda sid: {"catchment_geometry_available": True, "catchment_geometry_status":"ok", "catchment_feature_count":1, "catchment_area_geometry_km2": 1, "catchment_signature":"x"})
    gap_cell = _cell(coords=[[0.05,0.05],[0.08,0.05],[0.08,0.08],[0.05,0.08],[0.05,0.05]])
    row = h._precip_from_cells(_station(), [gap_cell])
    assert row["contributing_cell_count"] == 0
    assert row["precip_status"] == "no_relevant_cell"


def test_empty_cell_list_keeps_valid_catchment(monkeypatch):
    from shapely.geometry import Polygon
    catchment = Polygon([(0,0),(0.1,0),(0.1,0.1),(0,0.1),(0,0)])
    monkeypatch.setattr(h.__import__("hydro_impact"), "load_station_catchment_index", lambda force_reload=False: {"S1": {"station_id":"S1", "geometry": catchment, "feature_count":1, "status":"ok", "area_km2": 1, "signature":"x", "properties":{}}})
    monkeypatch.setattr(h.__import__("hydro_impact"), "catchment_diagnostics", lambda sid: {"catchment_geometry_available": True, "catchment_geometry_status":"ok", "catchment_feature_count":1, "catchment_area_geometry_km2": 1, "catchment_signature":"x"})
    row = h._precip_from_cells(_station(), [])
    assert row["catchment_geometry_available"] is True
    assert row["precip_evaluable_by_geometry"] is True
    assert row["precip_status"] == "no_relevant_cell"
    assert row["effective_overlap_area_km2"] == 0
    assert row["physical_predicted_q_max_m3s"] == 10.0
