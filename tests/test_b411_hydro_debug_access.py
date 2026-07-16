import hydro_flood_ml as h


def test_debug_evaluation_does_not_write_public_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(h, 'HYDRO_RISK_PATH', tmp_path/'risk.json')
    monkeypatch.setattr(h, 'readiness_status', lambda: {})
    monkeypatch.setattr(h, 'record_pending_samples', lambda *a, **k: {'pending_added':0})
    monkeypatch.setattr(h, 'materialize_pending_samples', lambda *a, **k: {'labeled_added':0})
    monkeypatch.setattr(h, 'build_feature_row', lambda *a, **k: {'station_id':'1','current_q_m3s':1,'station_q_threshold_m3s':2,'catchment_geometry_available':True,'physical_predicted_q_delta_m3s':0,'physical_predicted_q_max_m3s':1,'cell_diagnostics':[{}]})
    h.evaluate_live_flood_risk(stations=[{'station_id':'1'}], write=True, include_debug=True)
    assert not h.HYDRO_RISK_PATH.exists()
    public=h.evaluate_live_flood_risk(stations=[{'station_id':'1'}], write=True, include_debug=False)
    assert public['payload_scope'] == 'public'
    assert 'debug_stations' not in public
    assert 'cell_diagnostics' not in public['stations'][0]
