import json

from hydro_static_import import build_static_hydro, hydro_json_to_geojson


def test_hydro_json_to_geojson_normalizes_station_points():
    gj = hydro_json_to_geojson({"stations": [{"id": 7, "name": "Test", "river": "Drau", "lon": 14.1, "lat": 46.7}]})
    assert gj["type"] == "FeatureCollection"
    assert gj["features"][0]["properties"]["station_id"] == "7"
    assert gj["features"][0]["geometry"]["coordinates"] == [14.1, 46.7]


def test_build_static_hydro_missing_inputs_writes_explainable_status(tmp_path):
    status = build_static_hydro(str(tmp_path))
    assert status["status"] == "hydro_static_missing"
    status_file = tmp_path / "generated" / "hydro_static_status.json"
    assert status_file.exists()
    saved = json.loads(status_file.read_text())
    assert "Hydro-Impact" in saved["message"]
