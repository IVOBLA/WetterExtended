import pytest
pytest.importorskip("flask")

@pytest.fixture
def client():
    import app as app_module
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()

import json
from pathlib import Path


def test_hydro_status_and_stations(client, monkeypatch, tmp_path):
    import hydro_api
    gen = tmp_path / 'static' / 'generated'; live = tmp_path / 'live'; impact = tmp_path / 'impact'
    gen.mkdir(parents=True); live.mkdir(); impact.mkdir()
    (gen/'station_network_index.json').write_text(json.dumps({'stations':[{'station_id':'S1','station_name':'Pegel A','river_name':'Gail','lon':13.1,'lat':46.6,'enabled':True}]}), encoding='utf-8')
    (live/'latest_hydro.json').write_text(json.dumps({'fetched_at':'2026-06-19T10:00:00Z','stations':[{'station_id':'S1','q_m3s':4.2,'w_cm':80,'measured_at':'2026-06-19T09:55:00Z'}]}), encoding='utf-8')
    (live/'hydro_status.json').write_text(json.dumps({'updated_at':'2026-06-19T10:00:00Z','error':None}), encoding='utf-8')
    (impact/'latest_hydro_impacts.json').write_text(json.dumps([{'event_id':'e1','cell_id':'C1','station_id':'S1','impact_score':0.7,'confidence':'high','status':'pending','reason':['x'],'estimated_lag_min':[20,180],'relation':'upstream_catchment_hit'}]), encoding='utf-8')
    monkeypatch.setattr(hydro_api, 'STATIC_GENERATED', gen); monkeypatch.setattr(hydro_api, 'LIVE_LATEST', live/'latest_hydro.json'); monkeypatch.setattr(hydro_api, 'LIVE_STATUS', live/'hydro_status.json'); monkeypatch.setattr(hydro_api, 'IMPACT_DIR', impact); monkeypatch.setattr(hydro_api, 'LATEST_IMPACTS', impact/'latest_hydro_impacts.json'); monkeypatch.setattr(hydro_api, 'VERIFICATIONS', impact/'hydro_verifications.jsonl')
    st = client.get('/api/hydro/status')
    assert st.status_code == 200
    assert st.get_json()['station_count'] == 1
    stations = client.get('/api/hydro/stations').get_json()
    assert stations['type'] == 'FeatureCollection'
    assert stations['features'][0]['properties']['impact_active'] is True
    latest = client.get('/api/hydro/impacts/latest').get_json()
    assert latest[0]['score'] == 0.7
