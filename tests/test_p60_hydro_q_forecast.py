"""P60 — Prognostizierter Pegel-Abfluss q_forecast (m3/s) nach Rational-Methode.

Unit-Tests der reinen Funktion + Integration in evaluate_hydro_forecast_impact.
"""

import pytest
import hydro_impact


def test_rational_formula_reference():
    out = hydro_impact.compute_q_forecast_m3s(8.0, 20.0, 5.0, 0.4, 1.0)
    assert out["delta_q_m3s"] == 11.111
    assert out["q_forecast_m3s"] == 19.111


def test_no_current_yields_none_qforecast():
    out = hydro_impact.compute_q_forecast_m3s(None, 20.0, 5.0, 0.4, 1.0)
    assert out["q_forecast_m3s"] is None
    assert out["delta_q_m3s"] == 11.111


def test_no_rain_delta_zero():
    out = hydro_impact.compute_q_forecast_m3s(8.0, 0.0, 5.0, 0.4, 1.0)
    assert out == {"delta_q_m3s": 0.0, "q_forecast_m3s": 8.0}


def test_attenuation_scales_delta():
    out = hydro_impact.compute_q_forecast_m3s(8.0, 20.0, 5.0, 0.4, 0.5)
    assert out["delta_q_m3s"] == 5.556
    assert out["q_forecast_m3s"] == 13.556


def test_garbage_inputs_no_crash():
    out = hydro_impact.compute_q_forecast_m3s("x", None, None)
    assert out["delta_q_m3s"] == 0.0 and out["q_forecast_m3s"] is None


def _poly(w, s, e, n):
    return {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}


def _catchment():
    return {"type": "Feature", "geometry": _poly(13.1, 46.0, 13.3, 46.2),
            "properties": {"station_id": "S1", "catchment_id": "C1", "station_name": "Test",
                           "river": "Testbach", "upstream_catchment_ids": ["C1"],
                           "impact_eligible": True, "enabled": True, "quality": "ok",
                           "lat": 46.1, "lon": 13.2}}


def _cell(rate=12.0):
    return {"id": 7, "cell_id": 7, "lat": 46.1, "lon": 12.7,
            "contour_geo": [[12.6, 46.0], [12.8, 46.0], [12.8, 46.2], [12.6, 46.2], [12.6, 46.0]],
            "nowcast_rain_rate_1h": rate,
            "forecast_lat_10": 46.1, "forecast_lon_10": 12.9,
            "forecast_lat_20": 46.1, "forecast_lon_20": 13.1,
            "forecast_lat_30": 46.1, "forecast_lon_30": 13.2,
            "forecast_lat_40": 46.1, "forecast_lon_40": 13.3,
            "forecast_lat_60": 46.1, "forecast_lon_60": 13.6}


def _cfg(monkeypatch, latest_hydro, **over):
    base = {"HYDRO_FORECAST_IMPACT_ENABLED": True, "HYDRO_STATION_OVERRIDES": {},
            "HYDRO_FORECAST_HORIZONS_MIN": [10, 20, 30, 40, 60],
            "HYDRO_FORECAST_PRECIP_REF_MM": 15.0, "HYDRO_FORECAST_MIN_PRECIP_MM_H": 1.0,
            "HYDRO_FORECAST_SINGLE_HIT_DWELL_MIN": 10.0,
            "HYDRO_FORECAST_RUNOFF_COEFF": 0.4, "HYDRO_FORECAST_ROUTING_ATTENUATION": 1.0,
            "HYDRO_MIN_OVERLAP_AREA_KM2": 1.0, "HYDRO_MIN_OVERLAP_RATIO_CELL": 0.05}
    base.update(over)
    monkeypatch.setattr(hydro_impact, "_runtime_get", lambda k, d=None: base.get(k, d))
    monkeypatch.setattr(hydro_impact, "_runtime_float", lambda k, d=None: float(base.get(k, d)))
    monkeypatch.setattr(hydro_impact, "hydro_enabled", lambda: True)
    monkeypatch.setattr(hydro_impact, "static_data_available", lambda: True)
    monkeypatch.setattr(hydro_impact, "_load_catchments", lambda: [_catchment()])
    def _lj(path, default=None):
        if path == hydro_impact.LATEST_HYDRO_PATH:
            return latest_hydro
        return default
    monkeypatch.setattr(hydro_impact, "_load_json", _lj)


@pytest.mark.skipif(not hydro_impact.SHAPELY_AVAILABLE, reason="Shapely fehlt")
def test_event_enriched_with_q_forecast(monkeypatch):
    latest = {"stations": [{"station_id": "S1", "q_m3s": 8.0}]}
    _cfg(monkeypatch, latest)
    ev = hydro_impact.evaluate_hydro_forecast_impact([_cell(rate=12.0)], "2026-06-24_12-00-00")
    assert len(ev) == 1
    e = ev[0]
    assert e["q_current_m3s"] == 8.0
    assert e["lead_min"] == e["first_hit_lead_min"]
    expected = round(8.0 + 0.4 * e["precip_rate_mm_h"] * e["max_overlap_area_km2"] / 3.6, 3)
    assert e["q_forecast_m3s"] == expected
    assert e["delta_q_m3s"] == round(expected - 8.0, 3)


@pytest.mark.skipif(not hydro_impact.SHAPELY_AVAILABLE, reason="Shapely fehlt")
def test_missing_q_current_keeps_forecast_none(monkeypatch):
    _cfg(monkeypatch, {"stations": []})
    ev = hydro_impact.evaluate_hydro_forecast_impact([_cell(rate=12.0)], "2026-06-24_12-00-00")
    assert len(ev) == 1
    assert ev[0]["q_current_m3s"] is None
    assert ev[0]["q_forecast_m3s"] is None
    assert ev[0]["delta_q_m3s"] > 0.0


@pytest.mark.skipif(not hydro_impact.SHAPELY_AVAILABLE, reason="Shapely fehlt")
def test_disabled_no_enrichment(monkeypatch):
    _cfg(monkeypatch, {"stations": [{"station_id": "S1", "q_m3s": 8.0}]},
         HYDRO_FORECAST_IMPACT_ENABLED=False)
    assert hydro_impact.evaluate_hydro_forecast_impact([_cell()], "2026-06-24_12-00-00") == []
