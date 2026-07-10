"""B329: dem_slope_barrier_status aus get_dem_features() wird bis in das
Objekt-Dict (new_memory[obj_id]) durchgereicht, damit accuracy_tracker.py und
tools/diagnose_forecast_quality.py den Status auswerten koennen."""
from datetime import datetime, timedelta

import pytest


def test_get_dem_features_liefert_status_schluessel():
    """Regressionsschutz fuer den Rueckgabe-Vertrag von get_dem_features()."""
    dem_feature = pytest.importorskip("dem_feature")

    result = dem_feature.get_dem_features(46.6, 14.3, vx=0.0, vy=0.0)

    assert "dem_slope_barrier_status" in result
    assert result["dem_slope_barrier_status"] in (
        "computed",
        "dem_partial_coverage",
        "no_movement_vector",
        "dem_unavailable",
    )


def test_accuracy_tracker_detail_record_reicht_status_unveraendert_durch():
    """Prueft den realen Detail-Record-Pfad in accuracy_tracker.py."""
    at = pytest.importorskip("accuracy_tracker")

    ts = datetime(2026, 1, 1, 12, 0, 0)
    obj = {
        "id": "TEST01",
        "lat": 46.6,
        "lon": 14.3,
        "forecast_lat_10": 46.61,
        "forecast_lon_10": 14.31,
        "dem_elevation_m": 1200.0,
        "dem_slope_toward_cell": 0.01,
        "dem_barrier_ahead": 5.0,
        "dem_slope_barrier_status": "no_movement_vector",
    }

    record = at._detail_record(
        obj=obj,
        ts=ts,
        target_ts=ts + timedelta(minutes=10),
        horizon_min=10,
        matched=None,
        dist_km=None,
        match_src="none",
        no_target_frame=False,
        stale=False,
        effective_lead_min=10.0,
    )

    assert record["dem_slope_barrier_status"] == "no_movement_vector"
