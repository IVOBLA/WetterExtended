import json
import hydro_flood_ml as h

def test_pending_payload_comes_from_feature_row_without_geometry(monkeypatch,tmp_path):
    monkeypatch.setattr(h,"HYDRO_ML_DIR",tmp_path)
    monkeypatch.setattr(h,"HYDRO_SAMPLE_DB_PATH",tmp_path/"samples.sqlite3")
    diagnostics=[{"cell_id":"c2","lineage_id":"l2"},{"cell_id":"c1","lineage_id":"l1"}]
    monkeypatch.setattr(h,"_precip_from_cells",lambda station, cells, ledger_rows=None:{"cell_diagnostics":diagnostics,"contributing_cell_count":2,"cell_catchment_count":2,"cell_precip_source_type":"cell_derived","cell_catchment_precip_sum_mm":1.0,"cell_catchment_precip_weighted_sum_mm":1.0,"cell_catchment_max_intensity":2.0,"precip_evaluable_by_geometry":True,"precip_status":"cell_derived","precip_status_label":"x","catchment_geometry_available":True,"catchment_geometry_status":"ok","catchment_area_geometry_km2":1.0})
    station={"station_id":"s","q_m3s":1.0,"measured_at":"2026-01-01T00:00:00Z","catchment_area_km2":1.0}
    row=h.build_feature_row(station,cells=[{"id":"c1"},{"id":"c2"}])
    h.record_pending_samples([row])
    payload=h._db_rows("pending_samples")[0]
    assert payload["contributing_cell_ids"]==["c1","c2"]
    assert payload["contributing_lineage_ids"]==["l1","l2"]
    assert payload["precip_event_active"] is True and payload["precip_event_evaluable"] is True
    assert not any(key in json.dumps(payload) for key in ('contour_geo','geometry','coordinates'))
