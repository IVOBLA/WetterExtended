"""P61 — Warngrenzen-Ueberschreitung (gemessen/prognostiziert) + impact_source."""
import json
import pytest


def _setup(monkeypatch, tmp_path, q_m3s, mark_q, q_forecast, global_mark=None):
    import hydro_api, hydro_impact
    gen = tmp_path / 'static' / 'generated'; live = tmp_path / 'live'; impact = tmp_path / 'impact'
    gen.mkdir(parents=True); live.mkdir(); impact.mkdir()
    row = {'station_id': 'S1', 'station_name': 'Pegel A', 'river_name': 'Gail',
           'lon': 13.1, 'lat': 46.6, 'enabled': True, 'impact_eligible': True}
    if mark_q is not None:
        row['mark_q_m3s'] = mark_q
    (gen/'station_network_index.json').write_text(json.dumps({'stations': [row]}), encoding='utf-8')
    (live/'latest_hydro.json').write_text(json.dumps({'stations': [{'station_id': 'S1', 'q_m3s': q_m3s, 'w_cm': 80}]}), encoding='utf-8')
    (impact/'latest_hydro_impacts.json').write_text(json.dumps([]), encoding='utf-8')
    fc = [] if q_forecast is None else [{'station_id': 'S1', 'q_forecast_m3s': q_forecast}]
    (impact/'latest_hydro_forecast.json').write_text(json.dumps(fc), encoding='utf-8')

    def fake_runtime_get(key, default=None):
        if key == 'HYDRO_STATION_OVERRIDES':
            return {}
        if key == 'HYDRO_ENABLED':
            return True
        if key == 'HYDRO_MAP_MARK_Q_M3S':
            return global_mark
        return default
    monkeypatch.setattr(hydro_api.runtime_config, 'get', fake_runtime_get)
    monkeypatch.setattr(hydro_api, 'STATIC_GENERATED', gen)
    monkeypatch.setattr(hydro_api, 'LIVE_LATEST', live/'latest_hydro.json')
    monkeypatch.setattr(hydro_api, 'IMPACT_DIR', impact)
    monkeypatch.setattr(hydro_api, 'LATEST_IMPACTS', impact/'latest_hydro_impacts.json')
    monkeypatch.setattr(hydro_api, 'VERIFICATIONS', impact/'hydro_verifications.jsonl')
    monkeypatch.setattr(hydro_impact, 'LATEST_FORECAST_PATH', impact/'latest_hydro_forecast.json')
    return hydro_api


def _props(hydro_api):
    feats = hydro_api.station_features()['features']
    assert len(feats) == 1
    return feats[0]['properties']


def test_measured(monkeypatch, tmp_path):
    p = _props(_setup(monkeypatch, tmp_path, q_m3s=18.0, mark_q=15.0, q_forecast=None))
    assert p['q_current'] == 18.0 and p['q_threshold'] == 15.0
    assert p['q_threshold_exceeded'] is True
    assert p['impact_source'] == 'measured'


def test_forecast(monkeypatch, tmp_path):
    p = _props(_setup(monkeypatch, tmp_path, q_m3s=8.0, mark_q=15.0, q_forecast=18.0))
    assert p['q_forecast'] == 18.0
    assert p['q_threshold_exceeded'] is True
    assert p['impact_source'] == 'forecast'


def test_both(monkeypatch, tmp_path):
    p = _props(_setup(monkeypatch, tmp_path, q_m3s=18.0, mark_q=15.0, q_forecast=22.0))
    assert p['q_threshold_exceeded'] is True
    assert p['impact_source'] == 'both'


def test_inactive_below_threshold(monkeypatch, tmp_path):
    p = _props(_setup(monkeypatch, tmp_path, q_m3s=8.0, mark_q=15.0, q_forecast=10.0))
    assert p['q_threshold_exceeded'] is False
    assert p['impact_source'] is None


def test_no_threshold_never_active(monkeypatch, tmp_path):
    p = _props(_setup(monkeypatch, tmp_path, q_m3s=99.0, mark_q=None, q_forecast=99.0, global_mark=None))
    assert p['q_threshold'] is None
    assert p['q_threshold_exceeded'] is False
    assert p['impact_source'] is None


def test_global_threshold_used_when_no_station_mark(monkeypatch, tmp_path):
    p = _props(_setup(monkeypatch, tmp_path, q_m3s=20.0, mark_q=None, q_forecast=None, global_mark=15.0))
    assert p['q_threshold'] == 15.0
    assert p['q_threshold_exceeded'] is True
    assert p['impact_source'] == 'measured'


def test_boundary_equal_counts_as_exceeded(monkeypatch, tmp_path):
    p = _props(_setup(monkeypatch, tmp_path, q_m3s=15.0, mark_q=15.0, q_forecast=None))
    assert p['q_threshold_exceeded'] is True
