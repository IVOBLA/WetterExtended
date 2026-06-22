import json
import pytest
from pathlib import Path

import hydro_impact
import hydro_station_index
from hydro_station_index import build_station_index

FIX = Path(__file__).parent / "fixtures" / "hydro"


@pytest.mark.skipif(not hydro_station_index.SHAPELY_AVAILABLE, reason="Shapely fehlt: keine produktive Hydro-Catchment-Union")
def test_build_station_index_assigns_quality_and_outputs(tmp_path):
    status = build_station_index(
        str(FIX / "hydro_stations_sample.geojson"),
        str(FIX / "basins_sample.geojson"),
        str(FIX / "flowlines_sample.geojson"),
        str(tmp_path),
    )
    assert status["ok"] is True
    assert status["status"] == "upstream_topology_partial"
    data = json.loads((tmp_path / "station_network_index.json").read_text())
    stations = {s["station_id"]: s for s in data["stations"]}
    assert stations["S1"]["catchment_id"] == "B1"
    assert stations["S1"]["quality"] == "exact"
    assert stations["S1"]["topology_source"] == "conservative_declared_upstream_catchments"
    assert stations["S1"]["upstream_source_quality"] == "declared_upstream_catchment_ids_valid"
    assert stations["S1"]["flow_distance_available"] is False
    assert stations["S1"]["flow_distance_km"] is None
    assert stations["S2"]["catchment_id"] == "B2"
    assert stations["S3"]["quality"] == "unresolved"
    assert stations["S3"]["impact_eligible"] is False
    assert stations["S3"]["topology_source"] == "none"
    assert stations["S3"]["flow_distance_available"] is False
    assert stations["S3"]["flow_distance_km"] is None
    assert "no_hydrological_upstream_catchment_match" in stations["S3"]["reason"]
    assert stations["S3"]["nearest_basin_hint"]
    assert (tmp_path / "hydro_stations.geojson").exists()
    assert (tmp_path / "station_catchments.geojson").exists()
    assert (tmp_path / "hydro_static_status.json").exists()


@pytest.mark.skipif(not hydro_station_index.SHAPELY_AVAILABLE, reason="Shapely fehlt: keine produktive Hydro-Catchment-Union")
def test_hydro_static_status_ok_true_keeps_detailed_status(tmp_path):
    status = build_station_index(
        str(FIX / "hydro_stations_upstream_union.geojson"),
        str(FIX / "basins_adjacent_union.geojson"),
        None,
        str(tmp_path),
    )

    written_status = json.loads((tmp_path / "hydro_static_status.json").read_text(encoding="utf-8"))
    assert status["ok"] is True
    assert written_status["ok"] is True
    assert status["status"] in {
        "upstream_topology_partial",
        "hydro_static_ready",
    }
    assert written_status["status"] == status["status"]


def test_missing_basins_does_not_crash(tmp_path):
    status = build_station_index(str(FIX / "hydro_stations_sample.geojson"), None, None, str(tmp_path))
    assert status["status"] in {"hydro_static_missing", "upstream_topology_missing", "flowlines_missing"}
    data = json.loads((tmp_path / "station_network_index.json").read_text())
    assert all(s["quality"] == "unresolved" for s in data["stations"])


def test_shapely_missing_disables_productive_station_catchment(tmp_path, monkeypatch):
    monkeypatch.setattr(hydro_station_index, "SHAPELY_AVAILABLE", False)
    status = build_station_index(
        str(FIX / "hydro_stations_sample.geojson"),
        str(FIX / "basins_sample.geojson"),
        str(FIX / "flowlines_sample.geojson"),
        str(tmp_path),
    )
    assert status["status"] in {"hydro_static_missing", "upstream_topology_missing", "flowlines_missing"}
    data = json.loads((tmp_path / "station_network_index.json").read_text())
    assert all(s["impact_eligible"] is False for s in data["stations"])
    assert any("hydro_geometry_unavailable" in s["reason"] for s in data["stations"])


def test_station_inside_basin_without_upstream_topology_is_not_impact_eligible(tmp_path, monkeypatch):
    monkeypatch.setattr(hydro_station_index, "SHAPELY_AVAILABLE", True)
    status = build_station_index(
        str(FIX / "hydro_stations_basin_only.geojson"),
        str(FIX / "basins_without_upstream.geojson"),
        None,
        str(tmp_path),
    )

    assert status["status"] in {"hydro_static_missing", "upstream_topology_missing", "flowlines_missing"}
    data = json.loads((tmp_path / "station_network_index.json").read_text(encoding="utf-8"))
    station = data["by_station_id"]["S_BASIN_ONLY"]
    assert station["station_basin"] == "B_ONLY"
    assert station["catchment_id"] == station["station_basin"]
    assert station["upstream_catchment_ids"] == []
    assert station["topology_source"] == "none"
    assert station["upstream_source_quality"] == "missing"
    assert station["flow_distance_available"] is False
    assert station["flow_distance_km"] is None
    assert station["impact_eligible"] is False
    assert station["enabled"] is False
    assert "upstream_topology_missing" in station["reason"]
    assert "upstream_catchment_unavailable" in station["reason"]

    catchments = json.loads((tmp_path / "station_catchments.geojson").read_text(encoding="utf-8"))
    assert catchments["features"] == []

    monkeypatch.setattr(hydro_impact, "NETWORK_INDEX_PATH", tmp_path / "station_network_index.json")
    monkeypatch.setattr(hydro_impact, "CATCHMENTS_PATH", tmp_path / "station_catchments.geojson")
    monkeypatch.setattr(hydro_impact, "LATEST_HYDRO_PATH", tmp_path / "latest_hydro.json")
    (tmp_path / "latest_hydro.json").write_text('{"stations": []}', encoding="utf-8")

    cell_in_same_basin = {
        "id": "CELL_IN_B_ONLY",
        "status": "active",
        "intensity": "severe",
        "duration_min": 30,
        "contour_geo": [[13.9, 46.5], [14.1, 46.5], [14.1, 46.7], [13.9, 46.7]],
    }
    assert hydro_impact.evaluate_hydro_impact([cell_in_same_basin], "2026-06-19T12:00:00Z") == []


@pytest.mark.skipif(not hydro_station_index.SHAPELY_AVAILABLE, reason="Shapely fehlt: keine produktive Hydro-Catchment-Union")
def test_upstream_catchment_ids_create_valid_geometric_union_and_impacts(tmp_path, monkeypatch):
    status = build_station_index(
        str(FIX / "hydro_stations_upstream_union.geojson"),
        str(FIX / "basins_adjacent_union.geojson"),
        None,
        str(tmp_path),
    )

    assert status["ok"] is True
    assert status["status"] == "hydro_static_ready"
    catchments = json.loads((tmp_path / "station_catchments.geojson").read_text(encoding="utf-8"))
    assert len(catchments["features"]) == 1

    feature = catchments["features"][0]
    props = feature["properties"]
    assert props["station_id"] == "S_UNION"
    assert set(props["upstream_catchment_ids"]) == {"B1", "B2"}
    assert props["impact_eligible"] is True
    assert props["topology_source"] == "conservative_declared_upstream_catchments"
    assert props["upstream_source_quality"] == "declared_upstream_catchment_ids_valid"
    assert props["flow_distance_available"] is False
    assert props["flow_distance_km"] is None

    basins = json.loads((FIX / "basins_adjacent_union.geojson").read_text(encoding="utf-8"))["features"]
    basin_shapes = [hydro_station_index.shape(basin["geometry"]) for basin in basins]
    union_shape = hydro_station_index.shape(feature["geometry"])
    expected_union = hydro_station_index.unary_union(basin_shapes)
    assert union_shape.equals_exact(expected_union, tolerance=1e-9)
    assert union_shape.area == pytest.approx(sum(basin.area for basin in basin_shapes), rel=1e-9)
    assert all(union_shape.covers(basin) for basin in basin_shapes)

    monkeypatch.setattr(hydro_impact, "CATCHMENTS_PATH", tmp_path / "station_catchments.geojson")
    monkeypatch.setattr(hydro_impact, "NETWORK_INDEX_PATH", tmp_path / "station_network_index.json")
    monkeypatch.setattr(hydro_impact, "LATEST_HYDRO_PATH", tmp_path / "latest_hydro.json")
    monkeypatch.setenv("HYDRO_ENABLED", "true")

    cells = [
        {"id": "B1", "contour_geo": [[13.02, 46.02], [13.08, 46.02], [13.08, 46.08], [13.02, 46.08]], "intensity": "strong", "duration_min": 30},
        {"id": "B2", "contour_geo": [[13.12, 46.02], [13.18, 46.02], [13.18, 46.08], [13.12, 46.08]], "intensity": "strong", "duration_min": 30},
        {"id": "OUT", "contour_geo": [[13.30, 46.02], [13.36, 46.02], [13.36, 46.08], [13.30, 46.08]], "intensity": "strong", "duration_min": 30},
    ]
    events = hydro_impact.evaluate_hydro_impact(cells, "2026-06-19_09-00-00")

    assert {event["cell_id"] for event in events} == {"B1", "B2"}
    assert all(event["station_id"] == "S_UNION" for event in events)
    assert all(set(event["upstream_catchment_ids"]) == {"B1", "B2"} for event in events)


def test_flowline_snapping_alone_is_diagnostic_and_not_impact_eligible(tmp_path, monkeypatch):
    monkeypatch.setattr(hydro_station_index, "SHAPELY_AVAILABLE", True)
    status = build_station_index(
        str(FIX / "hydro_stations_basin_only.geojson"),
        str(FIX / "basins_without_upstream.geojson"),
        str(FIX / "flowlines_sample.geojson"),
        str(tmp_path),
    )

    assert status["status"] in {"hydro_static_missing", "upstream_topology_missing", "flowlines_missing"}
    data = json.loads((tmp_path / "station_network_index.json").read_text(encoding="utf-8"))
    station = data["by_station_id"]["S_BASIN_ONLY"]
    assert station["snapped_flowline_id"] is not None
    assert station["snap_distance_m"] is not None
    assert station["impact_eligible"] is False
    assert station["enabled"] is False
    assert station["topology_source"] == "none"
    assert station["upstream_source_quality"] == "missing"
    assert station["flow_distance_available"] is False
    assert station["flow_distance_km"] is None


def test_invalid_declared_upstream_ids_do_not_create_impact_eligibility(tmp_path, monkeypatch):
    monkeypatch.setattr(hydro_station_index, "SHAPELY_AVAILABLE", True)
    stations = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [14.0, 46.6]},
            "properties": {"station_id": "S_INVALID_UPSTREAM", "upstream_catchment_ids": ["DOES_NOT_EXIST"]},
        }],
    }
    stations_path = tmp_path / "stations_invalid_upstream.geojson"
    stations_path.write_text(json.dumps(stations), encoding="utf-8")

    build_station_index(str(stations_path), str(FIX / "basins_sample.geojson"), None, str(tmp_path))

    data = json.loads((tmp_path / "station_network_index.json").read_text(encoding="utf-8"))
    station = data["by_station_id"]["S_INVALID_UPSTREAM"]
    assert station["upstream_catchment_ids"] == []
    assert station["impact_eligible"] is False
    assert station["topology_source"] == "none"
    assert station["upstream_source_quality"] == "declared_upstream_catchment_ids_unresolved"
    assert station["flow_distance_available"] is False
    assert station["flow_distance_km"] is None


def test_ggn_uppercase_fields_set_station_basin_without_fake_impact(tmp_path):
    status = build_station_index(
        str(FIX / "hydro_stations_ggn.geojson"),
        str(FIX / "basins_ggn_no_upstream.geojson"),
        None,
        str(tmp_path),
    )

    assert status["status"] != "hydro_static_missing"
    assert status["station_basin_count"] == 1
    assert status["enabled_station_count"] == 0
    assert status["ok"] is False
    assert status["topology_source"] == "none"
    assert status["reason_summary"]["upstream_topology_missing"] is True

    data = json.loads((tmp_path / "station_network_index.json").read_text(encoding="utf-8"))
    station = data["by_station_id"]["S_GGN"]
    assert station["station_basin"] == "GGN_B1"
    assert station["catchment_id"] == station["station_basin"]
    assert station["impact_eligible"] is False
    assert station["source_quality"] in {"upstream_topology_missing", "hydro_geometry_unavailable"}

    catchments = json.loads((tmp_path / "station_catchments.geojson").read_text(encoding="utf-8"))
    assert catchments["features"] == []


@pytest.mark.skipif(not hydro_station_index.SHAPELY_AVAILABLE, reason="Shapely fehlt: keine produktive Hydro-Catchment-Union")
def test_ggn_explicit_upstream_relationship_enables_real_catchment(tmp_path, monkeypatch):
    monkeypatch.setattr(hydro_station_index, "SHAPELY_AVAILABLE", True)
    status = build_station_index(
        str(FIX / "hydro_stations_ggn.geojson"),
        str(FIX / "basins_ggn_upstream.geojson"),
        None,
        str(tmp_path),
    )

    assert status["ok"] is True
    assert status["status"] == "hydro_static_ready"
    assert status["station_basin_count"] == 1
    assert status["enabled_station_count"] == 1
    assert status["topology_source"] == "ggn_basin_attributes"

    data = json.loads((tmp_path / "station_network_index.json").read_text(encoding="utf-8"))
    station = data["by_station_id"]["S_GGN"]
    assert station["station_basin"] == "B_DOWN"
    assert station["impact_eligible"] is True
    assert set(station["upstream_catchment_ids"]) == {"B_DOWN", "B_UP"}
    assert station["topology_source"] == "ggn_basin_downstream_topology"

    catchments = json.loads((tmp_path / "station_catchments.geojson").read_text(encoding="utf-8"))
    assert len(catchments["features"]) == 1
    assert catchments["features"][0]["properties"]["source_schema"] == "GGN_DRAINAGEBASIN"
