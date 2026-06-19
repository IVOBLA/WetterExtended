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
    assert status["status"] == "ok"
    data = json.loads((tmp_path / "station_network_index.json").read_text())
    stations = {s["station_id"]: s for s in data["stations"]}
    assert stations["S1"]["catchment_id"] == "B1"
    assert stations["S1"]["quality"] in {"exact", "snapped"}
    assert stations["S2"]["catchment_id"] == "B2"
    assert stations["S3"]["quality"] == "unresolved"
    assert stations["S3"]["impact_eligible"] is False
    assert "no_hydrological_upstream_catchment_match" in stations["S3"]["reason"]
    assert stations["S3"]["nearest_basin_hint"]
    assert (tmp_path / "hydro_stations.geojson").exists()
    assert (tmp_path / "station_catchments.geojson").exists()
    assert (tmp_path / "hydro_static_status.json").exists()


def test_missing_basins_does_not_crash(tmp_path):
    status = build_station_index(str(FIX / "hydro_stations_sample.geojson"), None, None, str(tmp_path))
    assert status["status"] == "hydro_static_missing"
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
    assert status["status"] == "hydro_static_missing"
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

    assert status["status"] == "hydro_static_missing"
    data = json.loads((tmp_path / "station_network_index.json").read_text(encoding="utf-8"))
    station = data["by_station_id"]["S_BASIN_ONLY"]
    assert station["station_basin"] == "B_ONLY"
    assert station["catchment_id"] is None
    assert station["upstream_catchment_ids"] == []
    assert station["impact_eligible"] is False
    assert station["enabled"] is False
    assert "upstream_topology_missing" in station["reason"]
    assert "station_catchment_unavailable" in station["reason"]

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
