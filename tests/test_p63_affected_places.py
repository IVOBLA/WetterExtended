"""P63 — Betroffene Orte (Watchlist im Puffer um aktive Flussabschnitte) + Popup-Daten."""
import json
import pytest


def _line(coords):
    return {"type": "LineString", "coordinates": coords}


def _setup(monkeypatch, tmp_path, buffer_km=1.0, watchlist=None):
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

    wl = watchlist if watchlist is not None else [
        {"name": "NahOrt", "lat": 46.72, "lon": 14.105, "radius_km": 2.0},
        {"name": "FernOrt", "lat": 46.72, "lon": 14.30, "radius_km": 2.0}]

    def fake_get(key, default=None):
        if key == "HYDRO_STATION_OVERRIDES": return {}
        if key == "HYDRO_ENABLED": return True
        if key == "HYDRO_MAP_MARK_Q_M3S": return None
        if key == "HYDRO_IMPACT_PLACE_BUFFER_KM": return buffer_km
        if key == "LOCATIONS_WATCHLIST": return wl
        return default
    monkeypatch.setattr(hydro_api.runtime_config, "get", fake_get)
    monkeypatch.setattr(hydro_api, "STATIC_GENERATED", gen)
    monkeypatch.setattr(hydro_api, "LIVE_LATEST", live/"latest_hydro.json")
    monkeypatch.setattr(hydro_api, "IMPACT_DIR", impact)
    monkeypatch.setattr(hydro_api, "LATEST_IMPACTS", impact/"latest_hydro_impacts.json")
    monkeypatch.setattr(hydro_api, "VERIFICATIONS", impact/"hydro_verifications.jsonl")
    monkeypatch.setattr(hydro_impact, "LATEST_FORECAST_PATH", impact/"latest_hydro_forecast.json")
    return hydro_api


def test_place_within_buffer_only(monkeypatch, tmp_path):
    api = _setup(monkeypatch, tmp_path, buffer_km=1.0)
    fc = api.affected_places()
    names = [f["properties"]["place_name"] for f in fc["features"]]
    assert names == ["NahOrt"]
    p = fc["features"][0]["properties"]
    assert p["station_id"] == "S1" and p["river"] == "Tiebel" and p["impact_source"] == "measured"
    assert p["distance_to_river_km"] <= 1.0 and p["distance_to_station_km"] is not None
    assert p["q_current"] == 20.0 and p["q_threshold"] == 15.0


def test_buffer_override_widens(monkeypatch, tmp_path):
    api = _setup(monkeypatch, tmp_path, buffer_km=20.0)
    names = sorted(f["properties"]["place_name"] for f in api.affected_places()["features"])
    assert names == ["FernOrt", "NahOrt"]


def test_segments_include_affected_place_names(monkeypatch, tmp_path):
    api = _setup(monkeypatch, tmp_path, buffer_km=1.0)
    seg = api.impact_segments()["features"][0]
    assert seg["properties"]["affected_places"] == ["NahOrt"]


def test_inactive_station_no_places(monkeypatch, tmp_path):
    api = _setup(monkeypatch, tmp_path, buffer_km=20.0)
    (tmp_path/"live"/"latest_hydro.json").write_text(json.dumps({"fetched_at": "x",
        "stations": [{"station_id": "S1", "q_m3s": 5.0}]}), encoding="utf-8")
    assert api.affected_places()["features"] == []
