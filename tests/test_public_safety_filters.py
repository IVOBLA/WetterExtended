import json
import math
import zipfile

import pytest


def _cell(**kw):
    base = {"id":"C1","lat":46.7,"lon":14.2,"contour_geo":[[14.1,46.6],[14.2,46.6],[14.2,46.7]],"missing":0}
    base.update(kw)
    return base


def test_forecast_plausibility_rejects_unrealistic_ml_jump(monkeypatch):
    import prediction
    obj = _cell(id="8Q5MI26V", speed_kmh=20)
    ok, reason, metrics = prediction.validate_forecast_point(obj, 10, 47.15, 14.9, mode="ml")
    assert ok is False
    assert reason == "ml_forecast_speed_exceeds_limit"
    assert metrics["forecast_speed_kmh"] > 150


def test_forecast_outside_bbox_and_non_finite_rejected():
    import prediction
    obj = _cell()
    assert prediction.validate_forecast_point(obj, 10, 50.0, 14.0, "ml")[1] == "ml_forecast_outside_bbox"
    assert prediction.validate_forecast_point(obj, 10, math.nan, 14.0, "ml")[1] == "ml_forecast_non_finite"


def test_forecast_reactivation_warmup_disables_ml(monkeypatch):
    import prediction
    monkeypatch.setattr(prediction._runtime_cfg, "get", lambda k, d=None: 3 if k == "ML_REACTIVATION_WARMUP_FRAMES" else d)
    obj = _cell(reactivated_from_inactive=True, reactivation_frames=1)
    assert prediction.validate_forecast_point(obj, 10, 46.71, 14.21, "ml")[1] == "reactivation_warmup"


def test_valid_ml_forecast_remains_valid():
    import prediction
    ok, reason, metrics = prediction.validate_forecast_point(_cell(), 10, 46.71, 14.21, "ml")
    assert ok is True
    assert reason is None
    assert metrics["forecast_speed_kmh"] < 150


def test_api_objects_excludes_silent_cells_by_default_and_requires_admin(monkeypatch):
    pytest.importorskip("flask")
    import app as app_module
    app_module.app.config.update(TESTING=True)
    monkeypatch.setattr(app_module, "_objects_for_ts", lambda ts: [_cell(id="A"), _cell(id="S", tracking_state="inactive_rain")])
    c = app_module.app.test_client()
    ids = [o["id"] for o in c.get("/api/objects").get_json()]
    assert ids == ["A"]
    r = c.get("/api/objects?include_silent=1")
    assert r.status_code == 403


def test_api_forecast_excludes_inactive_rain_cells(monkeypatch):
    pytest.importorskip("flask")
    import app as app_module
    app_module.app.config.update(TESTING=True)
    active = _cell(id="A", forecast_lat_10=46.71, forecast_lon_10=14.21)
    silent = _cell(id="S", tracking_state="inactive_rain", forecast_lat_10=46.71, forecast_lon_10=14.21)
    monkeypatch.setattr(app_module, "_objects_for_ts", lambda ts: [active, silent])
    data = app_module.app.test_client().get("/api/forecast").get_json()
    assert {f["properties"]["cell_id"] for f in data["features"]} == {"A"}


def test_kmz_excludes_silent_cells(tmp_path):
    pytest.importorskip("simplekml")
    from kmz_export import save_forecast_as_kmz
    out = tmp_path / "forecast.kmz"
    save_forecast_as_kmz({10: [{"id":"S","x":1,"y":1,"lat":46.7,"lon":14.2,"origin_lat":46.6,"origin_lon":14.1,"tracking_state":"inactive_rain"}]}, {}, str(out), current_objects=[_cell(id="S", tracking_state="inactive_rain")])
    with zipfile.ZipFile(out) as zf:
        text = "\n".join(zf.read(n).decode("utf-8", "ignore") for n in zf.namelist() if n.endswith(".kml"))
    assert "S" not in text


def test_hydro_disabled_station_not_public(monkeypatch, tmp_path):
    import hydro_api
    gen = tmp_path / 'static' / 'generated'; live = tmp_path / 'live'; impact = tmp_path / 'impact'
    gen.mkdir(parents=True); live.mkdir(); impact.mkdir()
    (gen/'station_network_index.json').write_text(json.dumps({'stations':[{'station_id':'S1','station_name':'Pegel A','lon':13.1,'lat':46.6,'enabled':True}]}), encoding='utf-8')
    (live/'latest_hydro.json').write_text(json.dumps({'stations':[{'station_id':'S1'}]}), encoding='utf-8')
    (impact/'latest_hydro_impacts.json').write_text(json.dumps([{'event_id':'e1','cell_id':'C1','station_id':'S1','status':'pending'}]), encoding='utf-8')
    monkeypatch.setattr(hydro_api, 'STATIC_GENERATED', gen); monkeypatch.setattr(hydro_api, 'LIVE_LATEST', live/'latest_hydro.json'); monkeypatch.setattr(hydro_api, 'IMPACT_DIR', impact); monkeypatch.setattr(hydro_api, 'LATEST_IMPACTS', impact/'latest_hydro_impacts.json'); monkeypatch.setattr(hydro_api, 'VERIFICATIONS', impact/'missing.jsonl')
    monkeypatch.setattr(hydro_api.runtime_config, 'get', lambda k, d=None: {'S1': {'enabled': False}} if k == 'HYDRO_STATION_OVERRIDES' else d)
    assert hydro_api.station_features()['features'] == []
    props = hydro_api.station_features(include_disabled=True)['features'][0]['properties']
    assert props['impact_active'] is False
    assert props['status'] == 'disabled'


def test_frontend_defensive_filters_present():
    from pathlib import Path
    txt = Path('frontend/src/pages/MapView.jsx').read_text(encoding='utf-8')
    assert 'function isPublicCell' in txt
    assert 'function isValidForecastFeature' in txt
    assert 'forecast_rejected' in txt


def test_hydro_station_patch_persists_only_station_overrides(monkeypatch, tmp_path):
    pytest.importorskip("flask")
    import app as app_module
    import runtime_config
    app_module.app.config.update(TESTING=True)
    monkeypatch.setattr(app_module, 'get_current_user', lambda: {'role': 'admin'})
    monkeypatch.setattr(runtime_config, '_get_path', lambda: str(tmp_path / 'runtime_overrides.json'))
    runtime_config.save({'FORECAST_MAX_SPEED_KMH': 120, 'GITHUB_VERIFY_CONFIG': {'token': 'must-not-grow'}})
    c = app_module.app.test_client()
    r = c.patch('/api/hydro/stations/S1', json={'enabled': False})
    assert r.status_code == 200
    stored = json.loads((tmp_path / 'runtime_overrides.json').read_text(encoding='utf-8'))
    assert stored['FORECAST_MAX_SPEED_KMH'] == 120
    assert stored['HYDRO_STATION_OVERRIDES'] == {'S1': {'enabled': False}}
    assert 'BBOX_KAERNTEN_EXTENDED' not in stored


def test_hydro_station_patch_rejects_invalid_fields_and_station_id(monkeypatch):
    pytest.importorskip("flask")
    import app as app_module
    app_module.app.config.update(TESTING=True)
    monkeypatch.setattr(app_module, 'get_current_user', lambda: {'role': 'admin'})
    c = app_module.app.test_client()
    assert c.patch('/api/hydro/stations/S1', json={'enabled': 'false'}).status_code == 400
    assert c.patch('/api/hydro/stations/bad/path', json={'enabled': False}).status_code == 404
    assert c.patch('/api/hydro/stations/S1', json={'unknown': 1}).status_code == 400
