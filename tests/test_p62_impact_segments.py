"""P62 — Flussabschnitt-Generat (station_river_segments.geojson) + impact_segments API."""
import json
import pytest
import hydro_station_index as hsi


def _poly(cx, cy, d=0.1):
    return {"type": "Polygon", "coordinates": [[[cx-d, cy-d], [cx+d, cy-d], [cx+d, cy+d], [cx-d, cy+d], [cx-d, cy-d]]]}


def _line(coords):
    return {"type": "LineString", "coordinates": coords}


def _write(p, obj):
    p.write_text(json.dumps(obj), encoding="utf-8")


@pytest.mark.skipif(not hsi.SHAPELY_AVAILABLE, reason="Shapely fehlt")
def test_segment_generated_from_topology(tmp_path):
    stations = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [13.2, 46.1]},
         "properties": {"station_id": "S1", "station_name": "Feldkirchen", "river_name": "Tiebel",
                        "upstream_catchment_ids": ["C_up"]}}]}
    basins = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": _poly(13.2, 46.1), "properties": {"catchment_id": "C_station"}},
        {"type": "Feature", "geometry": _poly(13.2, 46.35), "properties": {"catchment_id": "C_up"}}]}
    flowlines = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": _line([[13.2, 46.32], [13.2, 46.38]]), "properties": {"flowline_id": "F_up"}},
        {"type": "Feature", "geometry": _line([[13.2, 46.07], [13.2, 46.13]]), "properties": {"flowline_id": "F_st"}},
        {"type": "Feature", "geometry": _line([[10.0, 40.0], [10.0, 40.1]]), "properties": {"flowline_id": "F_far"}}]}
    sp = tmp_path/"st.geojson"; bp = tmp_path/"ba.geojson"; fp = tmp_path/"fl.geojson"; out = tmp_path/"gen"; out.mkdir()
    _write(sp, stations); _write(bp, basins); _write(fp, flowlines)
    status = hsi.build_station_index(str(sp), str(bp), str(fp), str(out))
    assert status["impact_eligible_station_count"] == 1
    seg = json.loads((out/"station_river_segments.geojson").read_text())
    assert len(seg["features"]) == 1
    f = seg["features"][0]
    assert f["properties"]["station_id"] == "S1"
    assert f["properties"]["river"] == "Tiebel"
    assert f["properties"]["segment_length_km"] > 0
    assert f["geometry"]["type"] in ("LineString", "MultiLineString")
    assert status["river_segment_count"] == 1


@pytest.mark.skipif(not hsi.SHAPELY_AVAILABLE, reason="Shapely fehlt")
def test_no_flowlines_empty_segments(tmp_path):
    stations = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [13.2, 46.1]},
         "properties": {"station_id": "S1", "upstream_catchment_ids": ["C_up"]}}]}
    basins = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": _poly(13.2, 46.1), "properties": {"catchment_id": "C_station"}},
        {"type": "Feature", "geometry": _poly(13.2, 46.35), "properties": {"catchment_id": "C_up"}}]}
    sp = tmp_path/"st.geojson"; bp = tmp_path/"ba.geojson"; out = tmp_path/"gen"; out.mkdir()
    _write(sp, stations); _write(bp, basins)
    hsi.build_station_index(str(sp), str(bp), None, str(out))
    seg = json.loads((out/"station_river_segments.geojson").read_text())
    assert seg["features"] == []


def test_impact_segments_api_only_active(monkeypatch, tmp_path):
    import hydro_api, hydro_impact
    gen = tmp_path/"static"/"generated"; live = tmp_path/"live"; impact = tmp_path/"impact"
    gen.mkdir(parents=True); live.mkdir(); impact.mkdir()
    _write(gen/"station_network_index.json", {"stations": [
        {"station_id": "S1", "station_name": "A", "river_name": "Tiebel", "lon": 13.2, "lat": 46.1,
         "enabled": True, "impact_eligible": True, "mark_q_m3s": 15.0},
        {"station_id": "S2", "station_name": "B", "river_name": "Gail", "lon": 13.3, "lat": 46.2,
         "enabled": True, "impact_eligible": True, "mark_q_m3s": 15.0}]})
    _write(gen/"station_river_segments.geojson", {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": _line([[13.2, 46.0], [13.2, 46.2]]),
         "properties": {"station_id": "S1", "station_name": "A", "river": "Tiebel", "segment_length_km": 2.0}},
        {"type": "Feature", "geometry": _line([[13.3, 46.1], [13.3, 46.3]]),
         "properties": {"station_id": "S2", "station_name": "B", "river": "Gail", "segment_length_km": 2.0}}]})
    _write(live/"latest_hydro.json", {"fetched_at": "2026-06-24T10:00:00Z", "stations": [
        {"station_id": "S1", "q_m3s": 20.0}, {"station_id": "S2", "q_m3s": 5.0}]})
    _write(impact/"latest_hydro_impacts.json", [])
    _write(impact/"latest_hydro_forecast.json", [])

    def fake_get(key, default=None):
        if key == "HYDRO_STATION_OVERRIDES": return {}
        if key == "HYDRO_ENABLED": return True
        if key == "HYDRO_MAP_MARK_Q_M3S": return None
        return default
    monkeypatch.setattr(hydro_api.runtime_config, "get", fake_get)
    monkeypatch.setattr(hydro_api, "STATIC_GENERATED", gen)
    monkeypatch.setattr(hydro_api, "LIVE_LATEST", live/"latest_hydro.json")
    monkeypatch.setattr(hydro_api, "IMPACT_DIR", impact)
    monkeypatch.setattr(hydro_api, "LATEST_IMPACTS", impact/"latest_hydro_impacts.json")
    monkeypatch.setattr(hydro_api, "VERIFICATIONS", impact/"hydro_verifications.jsonl")
    monkeypatch.setattr(hydro_impact, "LATEST_FORECAST_PATH", impact/"latest_hydro_forecast.json")

    fc = hydro_api.impact_segments()
    sids = [f["properties"]["station_id"] for f in fc["features"]]
    assert sids == ["S1"]
    p = fc["features"][0]["properties"]
    assert p["impact_source"] == "measured" and p["q_current"] == 20.0 and p["q_threshold"] == 15.0
    assert p["updated_at"] == "2026-06-24T10:00:00Z" and p["affected_places"] == []
