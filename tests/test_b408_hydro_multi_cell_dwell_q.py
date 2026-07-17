import json

import hydro_flood_ml
import hydro_impact


def setup_catch(tmp_path, monkeypatch):
    path=tmp_path/"station_catchments.geojson"
    path.write_text(json.dumps({"type":"FeatureCollection","features":[{"type":"Feature","properties":{"station_id":"s1"},"geometry":{"type":"Polygon","coordinates":[[[0,0],[1,0],[1,1],[0,1],[0,0]]]}}]}), encoding="utf-8")
    monkeypatch.setattr(hydro_impact, "CATCHMENTS_PATH", path); hydro_impact.load_station_catchment_index(True)


def cell(cid, x1, y1, x2, y2, rate=10, **kw):
    d={"id":cid,"lat":(y1+y2)/2,"lon":(x1+x2)/2,"contour_geo":[[x1,y1],[x2,y1],[x2,y2],[x1,y2]],"rain_rate_mm_h":rate}
    d.update(kw); return d


def eval_cells(cells, q=1.0):
    return hydro_flood_ml.evaluate_live_flood_risk(stations=[{"station_id":"s1","q_m3s":q,"mark_q_m3s":99}], cells=cells, write=False, include_debug=True)["stations"][0]


def test_incoming_cell_uses_productive_forecast_not_raw_ml(tmp_path, monkeypatch):
    setup_catch(tmp_path, monkeypatch)
    c=cell("in", 2, .2, 2.4, .6, forecast_lat_20=.4, forecast_lon_20=.4, forecast_mode_20="kinematic_fallback", forecast_ml_lat_20=5, forecast_ml_lon_20=5)
    st=eval_cells([c])
    assert st["current_cell_count"] == 0
    assert st["incoming_cell_count"] == 1
    assert 15 <= st["cell_diagnostics"][0]["entry_offset_min"] <= 20
    assert st["predicted_q_delta_m3s"] > 0


def test_separate_cells_add_and_starting_q_offsets_prediction(tmp_path, monkeypatch):
    setup_catch(tmp_path, monkeypatch)
    cells=[cell("a", .1,.1,.3,.3), cell("b", .7,.7,.9,.9)]
    one=eval_cells(cells, q=1.0); five=eval_cells(cells, q=5.0)
    assert one["contributing_cell_count"] == 2
    assert abs((five["predicted_q_max_m3s"] - one["predicted_q_max_m3s"]) - 4.0) < 0.01


def test_overlapping_cells_are_spatially_deduplicated(tmp_path, monkeypatch):
    setup_catch(tmp_path, monkeypatch)
    st=eval_cells([cell("weak", .2,.2,.8,.8, rate=5), cell("strong", .2,.2,.8,.8, rate=20)])
    assert st["contributing_cell_count"] == 2
    assert st["spatial_dedup_applied"] is True
    assert st["overlap_deduplicated_area_km2"] > 0
    assert st["effective_overlap_area_km2"] < st["raw_overlap_area_km2_sum"]
