"""P64 — Frontend-Contract: impact-segments/affected-places liefern die vom Karten-UI
konsumierten Property-Keys (Flussabschnitt-Layer, Ortssymbol-Layer, Popups)."""
import json


def _line(coords):
    return {"type": "LineString", "coordinates": coords}


def _setup(monkeypatch, tmp_path):
    import hydro_api, hydro_impact
    gen = tmp_path/"static"/"generated"; live = tmp_path/"live"; impact = tmp_path/"impact"
    gen.mkdir(parents=True); live.mkdir(); impact.mkdir()
    (gen/"station_network_index.json").write_text(json.dumps({"stations": [
        {"station_id": "S1", "station_name": "Feldkirchen", "river_name": "Tiebel", "lon": 14.10, "lat": 46.72,
         "enabled": True, "impact_eligible": True, "mark_q_m3s": 15.0}]}), encoding="utf-8")
    (gen/"station_river_segments.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": _line([[14.10, 46.70], [14.10, 46.74]]),
         "properties": {"station_id": "S1", "station_name": "Feldkirchen", "river": "Tiebel", "segment_length_km": 4.4}}]}), encoding="utf-8")
    (live/"latest_hydro.json").write_text(json.dumps({"fetched_at": "2026-06-24T10:00:00Z",
        "stations": [{"station_id": "S1", "q_m3s": 20.0}]}), encoding="utf-8")
    (impact/"latest_hydro_impacts.json").write_text("[]", encoding="utf-8")
    (impact/"latest_hydro_forecast.json").write_text("[]", encoding="utf-8")

    def fake_get(key, default=None):
        return {"HYDRO_STATION_OVERRIDES": {}, "HYDRO_ENABLED": True, "HYDRO_MAP_MARK_Q_M3S": None,
                "HYDRO_IMPACT_PLACE_BUFFER_KM": 1.0,
                "LOCATIONS_WATCHLIST": [{"name": "Feldkirchen", "lat": 46.723, "lon": 14.101, "radius_km": 2.0}]}.get(key, default)
    monkeypatch.setattr(hydro_api.runtime_config, "get", fake_get)
    monkeypatch.setattr(hydro_api, "STATIC_GENERATED", gen)
    monkeypatch.setattr(hydro_api, "LIVE_LATEST", live/"latest_hydro.json")
    monkeypatch.setattr(hydro_api, "IMPACT_DIR", impact)
    monkeypatch.setattr(hydro_api, "LATEST_IMPACTS", impact/"latest_hydro_impacts.json")
    monkeypatch.setattr(hydro_api, "VERIFICATIONS", impact/"hydro_verifications.jsonl")
    monkeypatch.setattr(hydro_impact, "LATEST_FORECAST_PATH", impact/"latest_hydro_forecast.json")
    return hydro_api


SEGMENT_KEYS = {"station_id", "station_name", "river", "impact_source",
                "q_current", "q_forecast", "q_threshold", "segment_length_km",
                "affected_places", "updated_at"}
PLACE_KEYS = {"place_name", "river", "station_id", "station_name", "impact_source",
              "distance_to_river_km", "distance_to_station_km", "q_current", "q_forecast", "q_threshold"}


def test_impact_segments_contract(monkeypatch, tmp_path):
    api = _setup(monkeypatch, tmp_path)
    fc = api.impact_segments()
    assert fc["type"] == "FeatureCollection" and len(fc["features"]) == 1
    f = fc["features"][0]
    assert f["geometry"]["type"] in ("LineString", "MultiLineString")
    assert SEGMENT_KEYS.issubset(set(f["properties"].keys()))
    assert f["properties"]["affected_places"] == ["Feldkirchen"]


def test_affected_places_contract(monkeypatch, tmp_path):
    api = _setup(monkeypatch, tmp_path)
    fc = api.affected_places()
    assert fc["type"] == "FeatureCollection" and len(fc["features"]) == 1
    f = fc["features"][0]
    assert f["geometry"]["type"] == "Point" and len(f["geometry"]["coordinates"]) == 2
    assert PLACE_KEYS.issubset(set(f["properties"].keys()))


def test_inactive_yields_empty_layers(monkeypatch, tmp_path):
    api = _setup(monkeypatch, tmp_path)
    (tmp_path/"live"/"latest_hydro.json").write_text(json.dumps({"fetched_at": "x",
        "stations": [{"station_id": "S1", "q_m3s": 5.0}]}), encoding="utf-8")
    assert api.impact_segments()["features"] == []
    assert api.affected_places()["features"] == []
