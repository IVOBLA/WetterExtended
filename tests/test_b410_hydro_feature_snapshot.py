import hydro_flood_ml as h

def test_feature_snapshot_complete_for_canonical_features(tmp_path, monkeypatch):
    monkeypatch.setattr(h, 'HYDRO_SAMPLE_DB_PATH', tmp_path/'s.sqlite3')
    monkeypatch.setattr(h, 'HYDRO_ML_DIR', tmp_path)
    row={k:1.0 for k in h.HYDRO_FLOOD_ML_FEATURES}
    row.update({'station_id':'s','current_q_m3s':1,'catchment_geometry_available':True,'current_q_measured_at':'2026-01-01T00:00:00Z'})
    h.record_pending_samples([row], cells_meta={'hash':'c'})
    sample=h._db_rows('pending_samples')[0]
    assert sample['feature_snapshot_complete'] is True
    assert 'upstream_catchment_count' in sample['features']
    assert 'cell_catchment_area_km2_sum' in sample['features']
    assert 'routing_tau_min' in sample['features']
