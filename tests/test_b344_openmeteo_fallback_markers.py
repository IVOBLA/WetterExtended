"""B344: Open-Meteo-Fallback-Werte werden als solche markiert (nicht mehr
ununterscheidbar von echten Nullwerten / echten Messwerten)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fetch_700hpa_wind_per_object_slim as w700
import fetch_arome_openmeteo as arome
import fetch_openmeteo_extended as ext
import fetch_synoptic_features as synoptic
import accuracy_tracker as at
from datetime import datetime


def test_700hpa_invalid_object_sets_markers():
    objs = [{"lat": None, "lon": None, "id": None}]
    w700.fetch_and_assign_700hpa_wind(objs, "2026-07-01_00-00-00")
    assert objs[0]["wind_speed_700hPa_fallback"] == 1
    assert objs[0]["wind_dir_cos_fallback"] == 1
    assert objs[0]["wind_dir_sin_fallback"] == 1
    assert objs[0]["wind_speed_700hPa"] == 0.0


def test_700hpa_except_branches_set_markers_in_source():
    with open("fetch_700hpa_wind_per_object_slim.py", encoding="utf-8") as f:
        src = f.read()
    fn = src.split("def fetch_and_assign_700hpa_wind(")[1].split("\ndef ")[0]
    assert fn.count("obj.update(_FALLBACK_MARKERS_700)") >= 5


def test_700hpa_parse_default_equality_marks_fallback_in_source():
    with open("fetch_700hpa_wind_per_object_slim.py", encoding="utf-8") as f:
        src = f.read()
    assert "if wind_vals == _DEFAULT_WIND:" in src


def test_arome_invalid_object_sets_markers():
    objs = [{"lat": None, "lon": None, "id": None}]
    arome.assign_arome_to_objects(objs, "2026-07-01_00-00-00")
    assert objs[0]["arome_t2m_fallback"] == 1
    assert objs[0]["arome_li_fallback"] == 1
    assert objs[0]["arome_t2m"] == 0.0


def test_arome_li_independent_marker_logic_in_source():
    with open("fetch_arome_openmeteo.py", encoding="utf-8") as f:
        src = f.read()
    assert 'obj["arome_li_fallback"] = 0 if li_value is not None else 1' in src
    assert "obj.update(_FALLBACK_MARKERS_AROME)" in src


def test_extended_marks_wind500_fallback_when_entries_b_missing():
    objs = [{"lat": 46.8, "lon": 14.3, "id": "X1"}]
    valid = [(0, objs[0])]
    ext._apply(None, None, None, None, valid, objs)
    assert objs[0]["wind_speed_500hPa_fallback"] == 1
    assert objs[0]["wind_speed_500hPa"] == 0.0


def test_extended_no_marker_when_entries_b_present():
    objs = [{"lat": 46.8, "lon": 14.3, "id": "X1"}]
    valid = [(0, objs[0])]
    data_b = [{"hourly": {"time": ["2026-07-01T00:00"], "wind_speed_500hPa": [42.0], "wind_direction_500hPa": [270.0], "wind_speed_850hPa": [30.0], "wind_direction_850hPa": [270.0], "temperature_500hPa": [-20.0], "temperature_700hPa": [-5.0]}}]
    ext._apply(None, data_b, None, None, valid, objs)
    assert "wind_speed_500hPa_fallback" not in objs[0]
    assert objs[0]["wind_speed_500hPa"] == 42.0


def test_synoptic_invalid_object_sets_marker():
    objs = [{"lat": None, "lon": None, "id": None}]
    synoptic.assign_synoptic_features(objs, "2026-07-01_00-00-00")
    assert objs[0]["wind_500_speed_fallback"] == 1
    assert objs[0]["wind_500_speed"] == 20.0


def test_synoptic_parse_equality_check_in_source():
    with open("fetch_synoptic_features.py", encoding="utf-8") as f:
        src = f.read()
    assert "if parsed == _DEFAULT:" in src
    assert "_FALLBACK_MARKERS_SYNOPTIC" in src


def _make_ts(s="2026-07-01_09-00-00"):
    return datetime.strptime(s, "%Y-%m-%d_%H-%M-%S")


def _call_detail_record(obj, matched=None, horizon=10, no_target=False):
    ts = _make_ts(); target_ts = _make_ts("2026-07-01_09-10-00")
    dist = 1.5 if matched else None
    return at._detail_record(obj, ts, target_ts, horizon, matched, dist, "id", no_target, False, float(horizon))


def test_detail_record_propagates_fallback_markers_true():
    obj = {"id": "T1", "lat": 46.8, "lon": 14.3, "origin_lat": 46.8, "origin_lon": 14.3, "forecast_lat_10": 46.82, "forecast_lon_10": 14.32, "wind_speed_700hPa": 0.0, "wind_speed_700hPa_fallback": 1, "wind_dir_cos": 0.0, "wind_dir_cos_fallback": 1, "wind_dir_sin": 0.0, "wind_dir_sin_fallback": 1, "arome_t2m": 0.0, "arome_t2m_fallback": 1, "arome_li": 0.0, "arome_li_fallback": 1, "wind_speed_500hPa": 0.0, "wind_speed_500hPa_fallback": 1}
    rec = _call_detail_record(obj, {"id": "T1", "lat": 46.81, "lon": 14.31})
    assert rec["wind_speed_700hPa_fallback"] is True
    assert rec["wind_dir_cos_fallback"] is True
    assert rec["wind_dir_sin_fallback"] is True
    assert rec["arome_t2m_fallback"] is True
    assert rec["arome_li_fallback"] is True
    assert rec["wind_speed_500hPa_fallback"] is True


def test_detail_record_markers_false_when_absent():
    obj = {"id": "T2", "lat": 46.8, "lon": 14.3, "origin_lat": 46.8, "origin_lon": 14.3, "forecast_lat_10": 46.82, "forecast_lon_10": 14.32, "wind_speed_700hPa": 45.0, "arome_t2m": 20.0, "wind_speed_500hPa": 55.0}
    rec = _call_detail_record(obj, {"id": "T2", "lat": 46.81, "lon": 14.31})
    assert rec["wind_speed_700hPa_fallback"] is False
    assert rec["arome_t2m_fallback"] is False
    assert rec["wind_speed_500hPa_fallback"] is False


def test_existing_fields_unchanged():
    obj = {"id": "T3", "lat": 46.8, "lon": 14.3, "origin_lat": 46.8, "origin_lon": 14.3, "forecast_lat_10": 46.82, "forecast_lon_10": 14.32, "cape": 1200.0, "nowcast_rr_mm15": 5.0, "lightning_count_10km": 3.0}
    rec = _call_detail_record(obj, {"id": "T3", "lat": 46.81, "lon": 14.31})
    assert rec["cape"] == 1200.0
    assert rec["nowcast_rr_mm15"] == 5.0
    assert rec["lightning_count_10km"] == 3.0
    assert "forecast_error_km" in rec
    assert "match_type" in rec
