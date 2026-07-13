"""B346: Restliche Open-Meteo-Fallback-Felder (fetch_openmeteo_extended.py,
fetch_synoptic_features.py) werden ebenfalls markiert."""
import os
import sys
import types

sys.modules.setdefault("requests", types.SimpleNamespace(get=lambda *args, **kwargs: None))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fetch_openmeteo_extended as ext
import fetch_synoptic_features as synoptic


def test_gust_fallback_marker_when_entries_a_missing():
    objs = [{"lat": 46.8, "lon": 14.3, "id": "X1"}]
    valid = [(0, objs[0])]
    ext._apply(None, None, None, None, valid, objs)
    assert objs[0]["wind_gust_10m_kmh_fallback"] == 1
    assert objs[0]["wind_gust_10m_kmh"] == 0.0


def test_pressure_block_sets_all_extended_markers_when_entries_b_missing():
    objs = [{"lat": 46.8, "lon": 14.3, "id": "X1"}]
    valid = [(0, objs[0])]
    ext._apply(None, None, None, None, valid, objs)
    for key in (
        "wind_speed_500hPa_fallback", "wind_dir_500_cos_fallback",
        "wind_dir_500_sin_fallback", "wind_speed_850hPa_fallback",
        "wind_dir_850_cos_fallback", "wind_dir_850_sin_fallback",
        "t500_c_fallback", "t700_c_fallback",
    ):
        assert objs[0][key] == 1, f"{key} fehlt/nicht 1"


def test_cin_pw_fallback_markers_when_entries_d_missing():
    objs = [{"lat": 46.8, "lon": 14.3, "id": "X1"}]
    valid = [(0, objs[0])]
    ext._apply(None, None, None, None, valid, objs)
    assert objs[0]["cin_fallback"] == 1
    assert objs[0]["pw_fallback"] == 1


def test_lpi_fallback_marker_when_entries_c_missing():
    objs = [{"lat": 46.8, "lon": 14.3, "id": "X1"}]
    valid = [(0, objs[0])]
    ext._apply(None, None, None, None, valid, objs)
    assert objs[0]["lpi_fallback"] == 1


def test_no_markers_when_all_requests_succeed():
    objs = [{"lat": 46.8, "lon": 14.3, "id": "X1"}]
    valid = [(0, objs[0])]
    data_a = [{"minutely_15": {"time": ["2026-07-01T00:00"], "wind_gusts_10m": [30.0]}}]
    data_b = [{
        "hourly": {
            "time": ["2026-07-01T00:00"],
            "wind_speed_500hPa": [42.0], "wind_direction_500hPa": [270.0],
            "wind_speed_850hPa": [30.0], "wind_direction_850hPa": [270.0],
            "temperature_500hPa": [-20.0], "temperature_700hPa": [-5.0],
        }
    }]
    data_c = [{"hourly": {"time": ["2026-07-01T00:00"], "lightning_potential": [5.0]}}]
    data_d = [{"hourly": {"time": ["2026-07-01T00:00"], "convective_inhibition": [10.0], "total_column_integrated_water_vapour": [15.0]}}]
    ext._apply(data_a, data_b, data_c, data_d, valid, objs)
    for key in (
        "wind_gust_10m_kmh_fallback", "wind_speed_500hPa_fallback",
        "wind_speed_850hPa_fallback", "cin_fallback", "pw_fallback", "lpi_fallback",
    ):
        assert key not in objs[0], f"{key} sollte bei erfolgreicher Response nicht gesetzt sein"


def test_synoptic_extended_markers_on_invalid_object():
    objs = [{"lat": None, "lon": None, "id": None}]
    synoptic.assign_synoptic_features(objs, "2026-07-01_00-00-00")
    assert objs[0]["z500_dam_fallback"] == 1
    assert objs[0]["wind_500_dir_cos_fallback"] == 1
    assert objs[0]["wind_500_dir_sin_fallback"] == 1
    assert objs[0]["wind_500_speed_fallback"] == 1
