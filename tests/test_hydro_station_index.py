import json
from pathlib import Path

from hydro_station_index import build_station_index

FIX = Path(__file__).parent / "fixtures" / "hydro"


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
