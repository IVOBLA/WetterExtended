"""B249 — DEM/Weather-Features in forecast_error_details.jsonl.

Tests:
- _detail_record enthält DEM-Felder (dem_elevation_m, dem_slope_toward_cell, etc.).
- _detail_record enthält Wetter-Felder (wind_speed_700hPa, cape, arome_li, etc.).
- Fehlende Werte im Objekt ergeben None (kein KeyError, kein Crash).
- Bestehende Felder (forecast_error_km, match_type usw.) bleiben unverändert.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import accuracy_tracker as at


def _make_ts(s="2026-06-24_09-00-00"):
    return datetime.strptime(s, "%Y-%m-%d_%H-%M-%S")


def _obj_with_features():
    return {
        "id": "TEST01",
        "lat": 46.8,
        "lon": 14.3,
        "origin_lat": 46.8,
        "origin_lon": 14.3,
        "forecast_lat_10": 46.85,
        "forecast_lon_10": 14.35,
        "radar_age_min": 2.5,
        # DEM
        "dem_elevation_m": 812.0,
        "dem_slope_toward_cell": 0.03,
        "dem_barrier_ahead": 150.0,
        "valley_alignment": 0.7,
        "terrain_blocking_score": 0.4,
        "orographic_lift_score": 0.6,
        # Wetter
        "wind_speed_700hPa": 45.0,
        "wind_dir_cos": 0.7,
        "wind_dir_sin": -0.7,
        "cape": 1200.0,
        "arome_li": -3.5,
        "arome_t2m": 28.0,
        "wind_speed_500hPa": 60.0,
        "nowcast_rr_mm15": 5.2,
        "lightning_count_10km": 3.0,
        "kinematic_speed_kmh": 42.0,
        "core_ratio": 0.55,
        "area": 180.0,
    }


def _matched():
    return {"id": "TEST01", "lat": 46.87, "lon": 14.37, "core_ratio": 0.4}


def _call_detail_record(obj, matched=None, horizon=10, no_target=False):
    ts = _make_ts()
    target_ts = _make_ts("2026-06-24_09-10-00")
    dist = 1.5 if matched else None
    return at._detail_record(obj, ts, target_ts, horizon, matched, dist, "id", no_target, False, float(horizon))


# ── DEM-Features vorhanden ────────────────────────────────────────────────────

def test_dem_elevation_present():
    rec = _call_detail_record(_obj_with_features(), _matched())
    assert "dem_elevation_m" in rec, "dem_elevation_m fehlt in _detail_record"
    assert rec["dem_elevation_m"] == 812.0


def test_dem_slope_present():
    rec = _call_detail_record(_obj_with_features(), _matched())
    assert "dem_slope_toward_cell" in rec
    assert abs(rec["dem_slope_toward_cell"] - 0.03) < 1e-6


def test_dem_barrier_present():
    rec = _call_detail_record(_obj_with_features(), _matched())
    assert "dem_barrier_ahead" in rec
    assert rec["dem_barrier_ahead"] == 150.0


def test_terrain_scores_present():
    rec = _call_detail_record(_obj_with_features(), _matched())
    assert "terrain_blocking_score" in rec
    assert "orographic_lift_score" in rec
    assert "valley_alignment" in rec


# ── Wetter-Features vorhanden ─────────────────────────────────────────────────

def test_wind_700hpa_present():
    rec = _call_detail_record(_obj_with_features(), _matched())
    assert "wind_speed_700hPa" in rec
    assert rec["wind_speed_700hPa"] == 45.0


def test_cape_arome_li_present():
    rec = _call_detail_record(_obj_with_features(), _matched())
    assert "cape" in rec and rec["cape"] == 1200.0
    assert "arome_li" in rec and rec["arome_li"] == -3.5


def test_nowcast_lightning_present():
    rec = _call_detail_record(_obj_with_features(), _matched())
    assert "nowcast_rr_mm15" in rec
    assert "lightning_count_10km" in rec


def test_core_ratio_area_present():
    rec = _call_detail_record(_obj_with_features(), _matched())
    assert "core_ratio" in rec and rec["core_ratio"] == 0.55
    assert "area" in rec and rec["area"] == 180.0


# ── Fehlende Werte → None, kein Crash ────────────────────────────────────────

def test_missing_dem_features_yield_none():
    """Objekt ohne DEM-Features → None-Werte, kein KeyError."""
    obj = {
        "id": "NODEM", "lat": 46.8, "lon": 14.3,
        "origin_lat": 46.8, "origin_lon": 14.3,
        "forecast_lat_10": 46.82, "forecast_lon_10": 14.32,
    }
    rec = _call_detail_record(obj, _matched())
    assert rec["dem_elevation_m"] is None
    assert rec["cape"] is None
    assert rec["arome_li"] is None


# ── Bestehende Felder unverändert ─────────────────────────────────────────────

def test_existing_fields_unchanged():
    rec = _call_detail_record(_obj_with_features(), _matched())
    assert "forecast_error_km" in rec
    assert "match_type" in rec
    assert "horizon_min" in rec
    assert "object_id" in rec
    assert rec["object_id"] == "TEST01"


def test_no_target_frame_still_works():
    """no_target_frame=True: neue Felder vorhanden, keine Exception."""
    obj = _obj_with_features()
    rec = _call_detail_record(obj, matched=None, no_target=True)
    assert rec["no_target_frame"] is True
    assert "dem_elevation_m" in rec
