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


def test_import_station_json_imports_local_file_without_network(tmp_path):
    import hydro_static_import
    source = tmp_path / "stations.json"
    source.write_text(json.dumps({"stations": [{"id": "A", "name": "Lokal", "lon": 14.2, "lat": 46.8}]}), encoding="utf-8")

    imported = hydro_static_import.import_station_json(str(source), str(tmp_path / "static"))

    assert imported.endswith("hydro_stations.geojson")
    saved = json.loads((tmp_path / "static" / "source" / "hydro_stations.geojson").read_text(encoding="utf-8"))
    assert saved["features"][0]["properties"]["station_id"] == "A"
    status = json.loads((tmp_path / "static" / "generated" / "hydro_static_status.json").read_text(encoding="utf-8"))
    assert status["status"] == "hydro_station_import_ok"
    assert status["source_type"] == "local_file"


def test_import_station_json_blocks_url_import_by_default(tmp_path):
    import hydro_static_import

    imported = hydro_static_import.import_station_json("https://example.invalid/stations.json", str(tmp_path))

    assert imported == ""
    assert not (tmp_path / "source" / "hydro_stations.geojson").exists()
    status = json.loads((tmp_path / "generated" / "hydro_static_status.json").read_text(encoding="utf-8"))
    assert status["status"] == "hydro_station_import_failed"
    assert status["source_type"] == "url"
    assert "URL-Import" in status["message"]


def test_import_station_json_manual_url_uses_retry_and_logger(tmp_path, monkeypatch):
    import sys
    import types
    import hydro_static_import

    calls = []

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}
        text = '{"stations": []}'
        url = "https://example.invalid/stations.json"
        request = type("Req", (), {"headers": {}})()

        def json(self):
            return {"stations": [{"id": 3, "name": "Mock", "lon": 14.3, "lat": 46.9}]}

    def fake_retry_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    def fake_logger(service, method, response, duration_ms=None, request_headers=None, fallback=False, error=None):
        calls.append(("logger", service, method, response.status_code, fallback, error))

    monkeypatch.setitem(sys.modules, "http_retry", types.SimpleNamespace(retry_get=fake_retry_get))
    monkeypatch.setitem(sys.modules, "external_response_logger", types.SimpleNamespace(
        persist_requests_response=fake_logger,
        persist_external_response=lambda *args, **kwargs: None,
    ))

    imported = hydro_static_import.import_station_json(
        "https://example.invalid/stations.json",
        str(tmp_path),
        allow_url_import=True,
    )

    assert imported.endswith("hydro_stations.geojson")
    assert calls[0][0] == "https://example.invalid/stations.json"
    assert calls[0][1]["service"] == "hydro_static_manual_import"
    assert calls[1][:4] == ("logger", "hydro", "GET", 200)
    saved = json.loads((tmp_path / "source" / "hydro_stations.geojson").read_text(encoding="utf-8"))
    assert saved["features"][0]["properties"]["station_id"] == "3"
