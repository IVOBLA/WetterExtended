import json
import hydro_static_import as h

def test_status_contains_extended_fields(tmp_path):
    st = h.status(str(tmp_path))
    for key in ("required_files", "downloads", "station_count", "basin_count", "flowline_count", "missing", "errors", "warnings"):
        assert key in st

def test_hydro_stations_geojson_from_live(tmp_path):
    src = tmp_path / "live.json"
    src.write_text(json.dumps({"source":"x","stations":[{"id":"S1","name":"Pegel","river":"Drau","lon":14,"lat":46.7,"q_m3s":1.2}]}), encoding="utf-8")
    out = h.import_station_json(str(src), str(tmp_path / "static"))
    assert out
    gj = json.loads((tmp_path / "static/source/hydro_stations.geojson").read_text(encoding="utf-8"))
    assert gj["features"][0]["properties"]["live_metadata"]["q_m3s"] == 1.2
