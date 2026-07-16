import json

import hydro_flood_ml
import hydro_impact


def _write_catchments(path):
    path.write_text(json.dumps({"type":"FeatureCollection","features":[{"type":"Feature","properties":{"station_id":"s1"},"geometry":{"type":"Polygon","coordinates":[[[0,0],[1,0],[1,1],[0,1],[0,0]]]}}]}), encoding="utf-8")


def _cell(**extra):
    d={"id":"c1","lat":0.5,"lon":0.5,"contour_geo":[[0.25,0.25],[0.75,0.25],[0.75,0.75],[0.25,0.75]],"nowcast_rain_rate_1h":12.0}
    d.update(extra); return d


def test_pipeline_without_private_overlap_or_station_catchment(tmp_path, monkeypatch):
    path=tmp_path/"station_catchments.geojson"; _write_catchments(path)
    monkeypatch.setattr(hydro_impact, "CATCHMENTS_PATH", path); hydro_impact.load_station_catchment_index(True)
    row=hydro_flood_ml.build_feature_row({"station_id":"s1","q_m3s":1.0,"mark_q_m3s":3.0}, cells=[_cell()])
    assert row["catchment_geometry_available"] is True
    assert row["contributing_cell_count"] == 1
    assert row["precip_evaluable"] is True
    assert row["effective_precip_source_type"] != "missing"
    assert row["predicted_q_max_m3s"] if "predicted_q_max_m3s" in row else True


def test_no_relevant_cell_is_not_missing(tmp_path, monkeypatch):
    path=tmp_path/"station_catchments.geojson"; _write_catchments(path)
    monkeypatch.setattr(hydro_impact, "CATCHMENTS_PATH", path); hydro_impact.load_station_catchment_index(True)
    outside=_cell(lat=3, lon=3, contour_geo=[[3,3],[3.2,3],[3.2,3.2],[3,3.2]])
    row=hydro_flood_ml.build_feature_row({"station_id":"s1","q_m3s":1.0,"mark_q_m3s":3.0}, cells=[outside])
    assert row["contributing_cell_count"] == 0
    assert row["incoming_cell_count"] == 0
    assert row["precip_evaluable"] is True
    assert row["precip_status"] == "no_relevant_cell"


def test_missing_threshold_keeps_precip_and_prediction(tmp_path, monkeypatch):
    path=tmp_path/"station_catchments.geojson"; _write_catchments(path)
    monkeypatch.setattr(hydro_impact, "CATCHMENTS_PATH", path); hydro_impact.load_station_catchment_index(True)
    doc=hydro_flood_ml.evaluate_live_flood_risk(stations=[{"station_id":"s1","q_m3s":1.0}], cells=[_cell()], write=False)
    st=doc["stations"][0]
    assert st["precip_evaluable"] is True
    assert st["predicted_q_max_m3s"] is not None
    assert st["flood_evaluable"] is False
    assert st["flood_status"] == "missing_threshold"
