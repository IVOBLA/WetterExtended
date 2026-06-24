"""P65 — ML-Gate: Catchment-/Upstream-Hydro-Features duerfen nur aus impact_eligible_auto
Stationen entstehen. Aktuell zieht die ML-Pipeline keinerlei Hydro-Features; dieser Guard
sichert die Invariante (1) verhaltensseitig an der einzigen Quelle (hydro_impact) und
(2) quellseitig fuer die ML-Feature-Module."""
import pathlib
import pytest
import hydro_impact

ROOT = pathlib.Path(__file__).resolve().parent.parent
ML_FEATURE_MODULES = ["dataset_builder.py", "compute_extra_features.py", "model_training.py", "ml_readiness.py"]
FORBIDDEN_HYDRO_TOKENS = ["upstream_catchment", "station_catchments", "compute_cell_catchment_overlap", "station_river_segments"]


def test_ml_feature_modules_contain_no_ungated_hydro_features():
    """Falls hier kuenftig Hydro-Features eingebaut werden, MUSS dieser Test angepasst und
    die Erzeugung explizit auf impact_eligible_auto gegatet werden (siehe hydro_impact)."""
    for mod in ML_FEATURE_MODULES:
        src = (ROOT / mod).read_text(encoding="utf-8")
        for tok in FORBIDDEN_HYDRO_TOKENS:
            assert tok not in src, f"{mod} referenziert {tok!r} ohne impact_eligible_auto-Gate (P65)"


def _poly(w, s, e, n):
    return {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}


def _catchment(eligible):
    return {"type": "Feature", "geometry": _poly(13.1, 46.0, 13.3, 46.2),
            "properties": {"station_id": "S1", "catchment_id": "C1", "station_name": "Test",
                           "river": "Testbach", "upstream_catchment_ids": ["C1"],
                           "impact_eligible": eligible, "impact_eligible_auto": eligible,
                           "enabled": True, "quality": "ok", "lat": 46.1, "lon": 13.2}}


def _cell():
    return {"id": 7, "cell_id": 7, "lat": 46.1, "lon": 13.2, "intensity": "severe",
            "duration_min": 30, "motion_direction_deg": 90,
            "contour_geo": [[13.1, 46.0], [13.3, 46.0], [13.3, 46.2], [13.1, 46.2], [13.1, 46.0]],
            "nowcast_rain_rate_1h": 12.0,
            "forecast_lat_10": 46.1, "forecast_lon_10": 13.2,
            "forecast_lat_20": 46.1, "forecast_lon_20": 13.2}


def _cfg(monkeypatch, eligible):
    base = {"HYDRO_FORECAST_IMPACT_ENABLED": True, "HYDRO_STATION_OVERRIDES": {},
            "HYDRO_FORECAST_HORIZONS_MIN": [10, 20], "HYDRO_FORECAST_MIN_PRECIP_MM_H": 1.0,
            "HYDRO_FORECAST_PRECIP_REF_MM": 15.0, "HYDRO_FORECAST_SINGLE_HIT_DWELL_MIN": 10.0,
            "HYDRO_FORECAST_RUNOFF_COEFF": 0.4, "HYDRO_FORECAST_ROUTING_ATTENUATION": 1.0,
            "HYDRO_MIN_OVERLAP_AREA_KM2": 1.0, "HYDRO_MIN_OVERLAP_RATIO_CELL": 0.05,
            "HYDRO_MIN_DURATION_MIN": 5, "HYDRO_RELEVANT_INTENSITIES": ["severe"]}
    monkeypatch.setattr(hydro_impact, "_runtime_get", lambda k, d=None: base.get(k, d))
    monkeypatch.setattr(hydro_impact, "_runtime_float", lambda k, d=None: float(base.get(k, d)))
    monkeypatch.setattr(hydro_impact, "hydro_enabled", lambda: True)
    monkeypatch.setattr(hydro_impact, "static_data_available", lambda: True)
    monkeypatch.setattr(hydro_impact, "_load_catchments", lambda: [_catchment(eligible)])
    monkeypatch.setattr(hydro_impact, "_load_json", lambda path, default=None: default)


@pytest.mark.skipif(not hydro_impact.SHAPELY_AVAILABLE, reason="Shapely fehlt")
def test_non_eligible_station_produces_no_measured_event(monkeypatch):
    _cfg(monkeypatch, eligible=False)
    assert hydro_impact.evaluate_hydro_impact([_cell()], "2026-06-24_12-00-00") == []


@pytest.mark.skipif(not hydro_impact.SHAPELY_AVAILABLE, reason="Shapely fehlt")
def test_eligible_station_produces_event(monkeypatch):
    _cfg(monkeypatch, eligible=True)
    assert len(hydro_impact.evaluate_hydro_impact([_cell()], "2026-06-24_12-00-00")) == 1


@pytest.mark.skipif(not hydro_impact.SHAPELY_AVAILABLE, reason="Shapely fehlt")
def test_non_eligible_station_produces_no_forecast_event(monkeypatch):
    _cfg(monkeypatch, eligible=False)
    assert hydro_impact.evaluate_hydro_forecast_impact([_cell()], "2026-06-24_12-00-00") == []
