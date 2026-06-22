import json


def test_hydro_api_core_status_and_geojson(monkeypatch, tmp_path):
    import hydro_api

    station_id = 'TEST-HYDRO-CORE-S1'

    def fake_runtime_get(key, default=None):
        if key == 'HYDRO_STATION_OVERRIDES':
            return {}
        if key == 'HYDRO_ENABLED':
            return True
        return default

    gen = tmp_path / 'static' / 'generated'; live = tmp_path / 'live'; impact = tmp_path / 'impact'
    gen.mkdir(parents=True); live.mkdir(); impact.mkdir()
    (gen/'station_network_index.json').write_text(json.dumps({'stations':[{'station_id':station_id,'station_name':'Pegel A','river_name':'Gail','lon':13.1,'lat':46.6,'enabled':True}]}), encoding='utf-8')
    (live/'latest_hydro.json').write_text(json.dumps({'fetched_at':'2026-06-19T10:00:00Z','stations':[{'station_id':station_id,'q_m3s':4.2,'w_cm':80,'measured_at':'2026-06-19T09:55:00Z'}]}), encoding='utf-8')
    (live/'hydro_status.json').write_text(json.dumps({'updated_at':'2026-06-19T10:00:00Z','error':None}), encoding='utf-8')
    (impact/'latest_hydro_impacts.json').write_text(json.dumps([{'event_id':'e1','cell_id':'C1','station_id':station_id,'impact_score':0.7,'confidence':'high','status':'pending','reason':['x'],'estimated_lag_min':[20,180],'relation':'upstream_catchment_hit'}]), encoding='utf-8')
    monkeypatch.setattr(hydro_api.runtime_config, 'get', fake_runtime_get)
    monkeypatch.setattr(hydro_api, 'STATIC_GENERATED', gen); monkeypatch.setattr(hydro_api, 'LIVE_LATEST', live/'latest_hydro.json'); monkeypatch.setattr(hydro_api, 'LIVE_STATUS', live/'hydro_status.json'); monkeypatch.setattr(hydro_api, 'IMPACT_DIR', impact); monkeypatch.setattr(hydro_api, 'LATEST_IMPACTS', impact/'latest_hydro_impacts.json'); monkeypatch.setattr(hydro_api, 'VERIFICATIONS', impact/'hydro_verifications.jsonl')
    assert hydro_api.status()['station_count'] == 1
    fc = hydro_api.station_features()
    assert len(fc['features']) == 1
    assert fc['features'][0]['properties']['station_id'] == station_id
    assert fc['features'][0]['properties']['impact_active'] is True
    assert hydro_api.normalized_impacts(True)[0]['score'] == 0.7


def test_hydro_station_features_hide_disabled_station_unless_requested(monkeypatch, tmp_path):
    import hydro_api

    def fake_runtime_get(key, default=None):
        if key == 'HYDRO_STATION_OVERRIDES':
            return {'S1': {'enabled': False}}
        if key == 'HYDRO_ENABLED':
            return True
        return default

    gen = tmp_path / 'static' / 'generated'; live = tmp_path / 'live'; impact = tmp_path / 'impact'
    gen.mkdir(parents=True); live.mkdir(); impact.mkdir()
    (gen/'station_network_index.json').write_text(json.dumps({'stations':[{'station_id':'S1','station_name':'Pegel A','river_name':'Gail','lon':13.1,'lat':46.6,'enabled':True}]}), encoding='utf-8')
    (live/'latest_hydro.json').write_text(json.dumps({'stations':[{'station_id':'S1','q_m3s':4.2,'w_cm':80}]}), encoding='utf-8')
    (impact/'latest_hydro_impacts.json').write_text(json.dumps([{'event_id':'e1','cell_id':'C1','station_id':'S1','impact_score':0.7,'status':'pending'}]), encoding='utf-8')
    monkeypatch.setattr(hydro_api.runtime_config, 'get', fake_runtime_get)
    monkeypatch.setattr(hydro_api, 'STATIC_GENERATED', gen); monkeypatch.setattr(hydro_api, 'LIVE_LATEST', live/'latest_hydro.json'); monkeypatch.setattr(hydro_api, 'IMPACT_DIR', impact); monkeypatch.setattr(hydro_api, 'LATEST_IMPACTS', impact/'latest_hydro_impacts.json'); monkeypatch.setattr(hydro_api, 'VERIFICATIONS', impact/'hydro_verifications.jsonl')

    assert hydro_api.station_features()['features'] == []
    fc = hydro_api.station_features(include_disabled=True)
    assert len(fc['features']) == 1
    props = fc['features'][0]['properties']
    assert props['station_id'] == 'S1'
    assert props['enabled'] is False
    assert props['impact_active'] is False


def test_api_hydro_stations_returns_visible_non_eligible_stations(monkeypatch, tmp_path):
    import hydro_api

    gen = tmp_path / 'static' / 'generated'; live = tmp_path / 'live'; impact = tmp_path / 'impact'
    gen.mkdir(parents=True); live.mkdir(); impact.mkdir()
    (gen/'station_network_index.json').write_text(json.dumps({'stations':[{'station_id':'S1','station_name':'Pegel A','river_name':'Gail','lon':13.1,'lat':46.6,'enabled':False,'impact_eligible':False,'source_quality':'upstream_topology_missing'}]}), encoding='utf-8')
    (live/'latest_hydro.json').write_text(json.dumps({'stations':[]}), encoding='utf-8')
    (impact/'latest_hydro_impacts.json').write_text(json.dumps([]), encoding='utf-8')
    monkeypatch.setattr(hydro_api.runtime_config, 'get', lambda k, d=None: {} if k == 'HYDRO_STATION_OVERRIDES' else (True if k == 'HYDRO_ENABLED' else d))
    monkeypatch.setattr(hydro_api, 'STATIC_GENERATED', gen); monkeypatch.setattr(hydro_api, 'LIVE_LATEST', live/'latest_hydro.json'); monkeypatch.setattr(hydro_api, 'IMPACT_DIR', impact); monkeypatch.setattr(hydro_api, 'LATEST_IMPACTS', impact/'latest_hydro_impacts.json'); monkeypatch.setattr(hydro_api, 'VERIFICATIONS', impact/'hydro_verifications.jsonl')
    props = hydro_api.station_features()['features'][0]['properties']
    assert props['enabled'] is True
    assert props['impact_eligible'] is False
    assert props['source_quality'] == 'upstream_topology_missing'


def test_api_hydro_stations_filters_only_explicit_disabled_override(monkeypatch, tmp_path):
    import hydro_api

    gen = tmp_path / 'static' / 'generated'; live = tmp_path / 'live'; impact = tmp_path / 'impact'
    gen.mkdir(parents=True); live.mkdir(); impact.mkdir()
    (gen/'station_network_index.json').write_text(json.dumps({'stations':[{'station_id':'S1','lon':13.1,'lat':46.6,'enabled':False,'impact_eligible':False},{'station_id':'S2','lon':13.2,'lat':46.7,'enabled':True,'impact_eligible':False}]}), encoding='utf-8')
    (live/'latest_hydro.json').write_text(json.dumps({'stations':[]}), encoding='utf-8')
    (impact/'latest_hydro_impacts.json').write_text(json.dumps([]), encoding='utf-8')
    monkeypatch.setattr(hydro_api.runtime_config, 'get', lambda k, d=None: {'S2': {'enabled': False}} if k == 'HYDRO_STATION_OVERRIDES' else (True if k == 'HYDRO_ENABLED' else d))
    monkeypatch.setattr(hydro_api, 'STATIC_GENERATED', gen); monkeypatch.setattr(hydro_api, 'LIVE_LATEST', live/'latest_hydro.json'); monkeypatch.setattr(hydro_api, 'IMPACT_DIR', impact); monkeypatch.setattr(hydro_api, 'LATEST_IMPACTS', impact/'latest_hydro_impacts.json'); monkeypatch.setattr(hydro_api, 'VERIFICATIONS', impact/'hydro_verifications.jsonl')
    ids = [f['properties']['station_id'] for f in hydro_api.station_features()['features']]
    assert ids == ['S1']
    assert hydro_api.station_features(include_disabled=True)['features'][1]['properties']['enabled'] is False


def test_empty_station_catchments_does_not_empty_station_endpoint(monkeypatch, tmp_path):
    import hydro_api

    gen = tmp_path / 'static' / 'generated'; live = tmp_path / 'live'; impact = tmp_path / 'impact'
    gen.mkdir(parents=True); live.mkdir(); impact.mkdir()
    (gen/'station_network_index.json').write_text(json.dumps({'stations':[{'station_id':'S1','lon':13.1,'lat':46.6,'impact_eligible':False,'source_quality':'upstream_topology_missing'}]}), encoding='utf-8')
    (gen/'station_catchments.geojson').write_text(json.dumps({'type':'FeatureCollection','features':[]}), encoding='utf-8')
    (live/'latest_hydro.json').write_text(json.dumps({'stations':[]}), encoding='utf-8')
    (impact/'latest_hydro_impacts.json').write_text(json.dumps([]), encoding='utf-8')
    monkeypatch.setattr(hydro_api.runtime_config, 'get', lambda k, d=None: {} if k == 'HYDRO_STATION_OVERRIDES' else (True if k == 'HYDRO_ENABLED' else d))
    monkeypatch.setattr(hydro_api, 'STATIC_GENERATED', gen); monkeypatch.setattr(hydro_api, 'LIVE_LATEST', live/'latest_hydro.json'); monkeypatch.setattr(hydro_api, 'IMPACT_DIR', impact); monkeypatch.setattr(hydro_api, 'LATEST_IMPACTS', impact/'latest_hydro_impacts.json'); monkeypatch.setattr(hydro_api, 'VERIFICATIONS', impact/'hydro_verifications.jsonl')
    assert len(hydro_api.catchments_all()['features']) == 0
    assert len(hydro_api.station_features()['features']) == 1
