import hydro_flood_ml as h

def test_public_payload_excludes_debug_series():
    row={'station_id':'1','cell_diagnostics':[{}],'station_runoff_series':[{}],'hit_intervals':[{}], 'current_q_m3s':1}
    public=h._public_flood_row(row)
    assert 'cell_diagnostics' not in public
    assert 'station_runoff_series' not in public
    assert 'hit_intervals' not in public
