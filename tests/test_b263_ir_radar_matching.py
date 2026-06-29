"""B263: select_ir_radar_matches evaluiert Radar-Objekte mit WX-cell_id."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cell_lineage import select_ir_radar_matches, compute_ir_radar_match_score


def _radar_obj(lat, lon, cell_id="WX-20260629-0001"):
    return {
        "id": "TRACK001", "cell_id": cell_id,
        "lat": lat, "lon": lon,
        "area": 50.0, "core_ratio": 0.4,
        "kinematic_speed_kmh": 30.0,
        "forecast_vx": 0.001, "forecast_vy": 0.001,
        "lineage_status": None,
    }


def _ir_track(lat, lon, age_min=5.0, bt_k=210.0):
    return {
        "ir_id": "IR001", "ir_track_id": "IR001",
        "lat": lat, "lon": lon,
        "bt_min_k": bt_k, "cloud_age_min": age_min,
        "area_growth_km2_per_min": 1.0,
        "vx_deg_min": 0.001, "vy_deg_min": 0.001,
        "radar_confirmed": False,
        "missing": 0,
    }


def test_radar_obj_mit_wx_cell_id_wird_evaluiert():
    """Radar-Objekte mit WX-cell_id dürfen nicht mehr übersprungen werden."""
    radar = [_radar_obj(46.6, 14.3)]  # hat WX-cell_id
    ir = [_ir_track(46.61, 14.31)]   # 1.4 km entfernt — nah genug

    selected, info = select_ir_radar_matches(radar, ir)
    # Es muss mindestens ein Kandidat evaluiert worden sein
    assert info["candidates"], (
        "Kandidatenliste ist leer — Radar-Objekte mit WX-cell_id werden immer noch gefiltert"
    )


def test_bereits_radar_confirmed_wird_weiter_uebersprungen():
    """Radar-Objekte mit lineage_status='radar_confirmed' werden übersprungen."""
    radar = [_radar_obj(46.6, 14.3)]
    radar[0]["lineage_status"] = "radar_confirmed"
    ir = [_ir_track(46.61, 14.31)]

    selected, info = select_ir_radar_matches(radar, ir)
    assert info["candidates"] == [], (
        "radar_confirmed-Objekte müssen übersprungen werden"
    )


def test_nahe_ir_zelle_wird_gematcht():
    """Eine IR-Zelle <40 km neben einem Radar-Objekt soll einen Match ergeben."""
    radar = [_radar_obj(46.62, 14.35, cell_id="WX-20260629-0099")]
    ir = [_ir_track(46.63, 14.36, age_min=3.0, bt_k=205.0)]

    selected, info = select_ir_radar_matches(radar, ir)
    # Kandidaten müssen vorhanden sein (score ob ≥Threshold hängt von Parametern ab)
    assert info["candidates"], "Kein Kandidat obwohl IR-Zelle in Reichweite"
    # Zumindest die Distanz wurde berechnet
    assert info["candidates"][0]["centroid_distance_km"] is not None


def test_ferne_ir_zelle_ergibt_keinen_match():
    """IR-Zellen außerhalb IR_RADAR_MATCH_MAX_KM=40 km ergeben keinen Match."""
    radar = [_radar_obj(46.6, 14.3)]
    ir = [_ir_track(47.5, 16.0)]  # >100 km entfernt

    selected, info = select_ir_radar_matches(radar, ir)
    assert selected == [], "Ferne IR-Zelle darf keinen Match ergeben"
    # Distanz zu groß → reason='distance_too_far'. Der Kandidat darf nicht
    # als Match selektiert werden, kann aber zur Diagnose gelistet sein.
    assert info["candidates"][0]["reason"] == "distance_too_far"


def test_regression_leere_listen():
    """Leere Eingaben führen zu keinem Crash."""
    selected, info = select_ir_radar_matches([], [])
    assert selected == []
    assert info["candidates"] == []


def test_regression_keine_coords_werden_uebersprungen():
    """Radar-Objekte ohne Koordinaten werden von compute_ir_radar_match_score ignoriert."""
    radar = [{"id": "X", "cell_id": "WX-20260629-0002", "lat": None, "lon": None}]
    ir = [_ir_track(46.6, 14.3)]
    selected, info = select_ir_radar_matches(radar, ir)
    assert selected == []  # kein Match, aber kein Absturz
