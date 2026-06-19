import json

import pytest

import hydro_impact


def _feature(station_id, w, s, e, n):
    return {
        "type": "Feature",
        "properties": {"station_id": station_id, "name": f"Pegel {station_id}", "river": "Drau", "impact_eligible": True, "source_quality": "upstream_union", "quality": "exact"},
        "geometry": {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]},
    }


def test_score_is_explained_and_confidence_is_transparent():
    cell = {"intensity": "strong", "duration_min": 20, "motion_direction_deg": 230}
    overlap = {"overlap_area_km2": 8.7, "overlap_ratio_cell": 0.22}

    scored = hydro_impact.score_hydro_impact(cell, {"valley_direction_deg": 225, "main_river_distance_km": 2}, overlap, {})

    assert scored["impact_score"] > 0.4
    assert scored["confidence"] in {"medium", "high"}
    assert "Schnittfläche über Mindestwert" in scored["reason"]
    assert "Intensität relevant" in scored["reason"]


def test_evaluate_ignores_tiny_or_irrelevant_intersections(tmp_path, monkeypatch):
    catchments = {"type": "FeatureCollection", "features": [_feature("123", 13.099, 46.099, 13.2, 46.2)]}
    cpath = tmp_path / "station_catchments.geojson"
    npath = tmp_path / "station_network_index.json"
    cpath.write_text(json.dumps(catchments), encoding="utf-8")
    npath.write_text(json.dumps({"123": {"impact_eligible": True, "quality": "exact", "estimated_lag_min": [20, 180]}}), encoding="utf-8")
    monkeypatch.setattr(hydro_impact, "CATCHMENTS_PATH", cpath)
    monkeypatch.setattr(hydro_impact, "NETWORK_INDEX_PATH", npath)
    monkeypatch.setattr(hydro_impact, "LATEST_HYDRO_PATH", tmp_path / "latest_hydro.json")
    monkeypatch.setattr(hydro_impact, "MIN_OVERLAP_AREA_KM2", 1.0)
    monkeypatch.setattr(hydro_impact, "MIN_OVERLAP_RATIO_CELL", 0.03)
    monkeypatch.setenv("HYDRO_ENABLED", "true")
    cell = {"id": 42, "contour_geo": [[13.0, 46.0], [13.1, 46.0], [13.1, 46.1], [13.0, 46.1], [13.0, 46.0]], "intensity": "strong", "duration_min": 15}

    assert hydro_impact.evaluate_hydro_impact([cell], "2026-06-19_09-00-00") == []


@pytest.mark.skipif(not hydro_impact.SHAPELY_AVAILABLE, reason="Shapely fehlt: produktive Hydro-Attribution wird konservativ deaktiviert")
def test_evaluate_creates_pending_event_only_for_upstream_catchment_hit(tmp_path, monkeypatch):
    catchments = {"type": "FeatureCollection", "features": [_feature("123", 13.05, 46.0, 13.2, 46.2)]}
    cpath = tmp_path / "station_catchments.geojson"
    npath = tmp_path / "station_network_index.json"
    cpath.write_text(json.dumps(catchments), encoding="utf-8")
    npath.write_text(json.dumps({"123": {"impact_eligible": True, "quality": "exact", "estimated_lag_min": [30, 120]}}), encoding="utf-8")
    monkeypatch.setattr(hydro_impact, "CATCHMENTS_PATH", cpath)
    monkeypatch.setattr(hydro_impact, "NETWORK_INDEX_PATH", npath)
    monkeypatch.setattr(hydro_impact, "LATEST_HYDRO_PATH", tmp_path / "latest_hydro.json")
    monkeypatch.setenv("HYDRO_ENABLED", "true")
    cell = {"id": 42, "contour_geo": [[13.0, 46.0], [13.2, 46.0], [13.2, 46.2], [13.0, 46.2], [13.0, 46.0]], "intensity": "strong", "duration_min": 15, "motion_direction_deg": 230}

    events = hydro_impact.evaluate_hydro_impact([cell], "2026-06-19_09-00-00")

    assert len(events) == 1
    assert events[0]["event_id"] == "hydro_20260619_090000_cell42_station123"
    assert events[0]["relation"] == "upstream_catchment_hit"
    assert events[0]["status"] == "pending"
    assert events[0]["verification"] is None


def test_evaluate_rejects_legacy_nearest_basin_fallback_station(tmp_path, monkeypatch):
    catchments = {"type": "FeatureCollection", "features": [_feature("123", 13.0, 46.0, 13.2, 46.2)]}
    cpath = tmp_path / "station_catchments.geojson"
    npath = tmp_path / "station_network_index.json"
    cpath.write_text(json.dumps(catchments), encoding="utf-8")
    npath.write_text(json.dumps({"123": {"enabled": True, "quality": "fallback_nearest_basin", "estimated_lag_min": [30, 120]}}), encoding="utf-8")
    monkeypatch.setattr(hydro_impact, "CATCHMENTS_PATH", cpath)
    monkeypatch.setattr(hydro_impact, "NETWORK_INDEX_PATH", npath)
    monkeypatch.setattr(hydro_impact, "LATEST_HYDRO_PATH", tmp_path / "latest_hydro.json")
    monkeypatch.setenv("HYDRO_ENABLED", "true")
    cell = {"id": 42, "contour_geo": [[13.0, 46.0], [13.2, 46.0], [13.2, 46.2], [13.0, 46.2], [13.0, 46.0]], "intensity": "strong", "duration_min": 15}

    assert hydro_impact.evaluate_hydro_impact([cell], "2026-06-19_09-00-00") == []
