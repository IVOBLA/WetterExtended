"""P57 — Vorausschauender Hydro-Impact: Forecast-Treffer im Einzugsgebiet,
gewichtet mit grober Niederschlagsmenge (Rate x Verweildauer)."""

import pytest
import hydro_impact


def _poly(w, s, e, n):
    return {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}


def _catchment():
    return {"type": "Feature", "geometry": _poly(13.1, 46.0, 13.3, 46.2),
            "properties": {"station_id": "S1", "catchment_id": "C1", "station_name": "Test",
                           "river": "Testbach", "upstream_catchment_ids": ["C1"],
                           "impact_eligible": True, "enabled": True, "quality": "ok",
                           "lat": 46.1, "lon": 13.2}}


def _cell(rate=12.0):
    return {
        "id": 7, "cell_id": 7, "lat": 46.1, "lon": 12.7,
        "contour_geo": [[12.6, 46.0], [12.8, 46.0], [12.8, 46.2], [12.6, 46.2], [12.6, 46.0]],
        "nowcast_rain_rate_1h": rate,
        "forecast_lat_10": 46.1, "forecast_lon_10": 12.9,
        "forecast_lat_20": 46.1, "forecast_lon_20": 13.1,
        "forecast_lat_30": 46.1, "forecast_lon_30": 13.2,
        "forecast_lat_40": 46.1, "forecast_lon_40": 13.3,
        "forecast_lat_60": 46.1, "forecast_lon_60": 13.6,
    }


def _cfg(monkeypatch, **over):
    base = {"HYDRO_FORECAST_IMPACT_ENABLED": True, "HYDRO_STATION_OVERRIDES": {},
            "HYDRO_FORECAST_HORIZONS_MIN": [10, 20, 30, 40, 60],
            "HYDRO_FORECAST_PRECIP_REF_MM": 15.0, "HYDRO_FORECAST_MIN_PRECIP_MM_H": 1.0,
            "HYDRO_FORECAST_SINGLE_HIT_DWELL_MIN": 10.0,
            "HYDRO_MIN_OVERLAP_AREA_KM2": 1.0, "HYDRO_MIN_OVERLAP_RATIO_CELL": 0.05}
    base.update(over)
    monkeypatch.setattr(hydro_impact, "_runtime_get", lambda k, d=None: base.get(k, d))
    monkeypatch.setattr(hydro_impact, "_runtime_float", lambda k, d=None: float(base.get(k, d)))
    monkeypatch.setattr(hydro_impact, "hydro_enabled", lambda: True)
    monkeypatch.setattr(hydro_impact, "static_data_available", lambda: True)
    monkeypatch.setattr(hydro_impact, "_load_catchments", lambda: [_catchment()])
    monkeypatch.setattr(hydro_impact, "_load_json", lambda path, default=None: default)


@pytest.mark.skipif(not hydro_impact.SHAPELY_AVAILABLE, reason="Shapely fehlt")
def test_forecast_hit_weighted_by_rate_and_dwell(monkeypatch):
    _cfg(monkeypatch)
    ev = hydro_impact.evaluate_hydro_forecast_impact([_cell(rate=12.0)], "2026-06-23_12-00-00")
    assert len(ev) == 1
    e = ev[0]
    assert e["relation"] == "forecast_upstream_catchment_hit" and e["status"] == "expected"
    assert e["first_hit_lead_min"] == 20
    assert e["forecast_dwell_min"] == 20.0
    assert e["precip_rate_mm_h"] == 12.0
    assert e["estimated_precip_mm"] == 4.0
    assert 0.0 < e["forecast_impact_score"] <= 1.0
    assert e["hit_horizons_min"] == [20, 30, 40]


@pytest.mark.skipif(not hydro_impact.SHAPELY_AVAILABLE, reason="Shapely fehlt")
def test_disabled_by_default(monkeypatch):
    _cfg(monkeypatch, HYDRO_FORECAST_IMPACT_ENABLED=False)
    assert hydro_impact.evaluate_hydro_forecast_impact([_cell()], "2026-06-23_12-00-00") == []


@pytest.mark.skipif(not hydro_impact.SHAPELY_AVAILABLE, reason="Shapely fehlt")
def test_weak_rain_filtered(monkeypatch):
    _cfg(monkeypatch, HYDRO_FORECAST_MIN_PRECIP_MM_H=5.0)
    assert hydro_impact.evaluate_hydro_forecast_impact([_cell(rate=0.4)], "2026-06-23_12-00-00") == []


@pytest.mark.skipif(not hydro_impact.SHAPELY_AVAILABLE, reason="Shapely fehlt")
def test_no_forecast_overlap_no_event(monkeypatch):
    _cfg(monkeypatch)
    c = _cell()
    for h in (10, 20, 30, 40, 60):
        c[f"forecast_lon_{h}"] = 11.0
    assert hydro_impact.evaluate_hydro_forecast_impact([c], "2026-06-23_12-00-00") == []


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    import hydro_impact as hi
    monkeypatch.setattr(hi, "LATEST_FORECAST_PATH", tmp_path / "latest_hydro_forecast.json")
    monkeypatch.setattr(hi, "IMPACT_DIR", tmp_path)
    hi.save_hydro_forecast_events([{"event_id": "x", "status": "expected"}])
    assert hi.load_latest_hydro_forecast() == [{"event_id": "x", "status": "expected"}]


def test_forecast_endpoint_public():
    pytest.importorskip("flask")
    import app as app_module
    app_module.app.config.update(TESTING=True)
    c = app_module.app.test_client()
    r = c.get("/api/hydro/forecast-impacts")
    assert r.status_code == 200
