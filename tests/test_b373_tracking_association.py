"""B373: globale Zuordnung, physikalische Gates in km/echter Zeit, Suchellipse."""
import pytest

from tracking.association import (
    DetectionCandidate,
    TrackCandidate,
    build_cost_matrix,
    passes_physical_gate,
    predict_track_state,
    solve_global_assignment,
)


def _trk(tid, x, y, vx=0.0, vy=0.0, area=1000.0, core=0.3, age=5):
    return TrackCandidate(track_id=tid, pred_x_km=x, pred_y_km=y, vx_kmh=vx, vy_kmh=vy,
                          area_px=area, core_ratio=core, age_frames=age)


def _det(i, x, y, area=1000.0, core=0.3):
    return DetectionCandidate(index=i, x_km=x, y_km=y, area_px=area, core_ratio=core)


def test_hungarian_beats_greedy_counterexample():
    """Der klassische Gegenfall: greedy waehlt X->A, global optimal ist X->B, Y->A."""
    a = _trk("A", 10.0, 10.0)
    b = _trk("B", 14.0, 10.0)
    x = _det(0, 12.0, 10.0)   # nahe an A UND B
    y = _det(1, 10.5, 10.0)   # praktisch nur bei A
    res = solve_global_assignment([a, b], [x, y], dt_minutes=5.0, max_speed_kmh=150.0)
    assert res.matches.get(1) == "A", "Y muss A bekommen (einziger sinnvoller Parent)"
    assert res.matches.get(0) == "B", "X muss global auf B ausweichen"


def test_result_is_order_invariant():
    """Die Zuordnung darf nicht von der Detektionsreihenfolge abhaengen."""
    a, b = _trk("A", 10.0, 10.0), _trk("B", 14.0, 10.0)
    x, y = _det(0, 12.0, 10.0), _det(1, 10.5, 10.0)
    r1 = solve_global_assignment([a, b], [x, y], 5.0, 150.0)
    r2 = solve_global_assignment([b, a], [y, x], 5.0, 150.0)
    assert r1.matches == r2.matches


def test_gate_uses_real_time_not_fixed_frame():
    """Bei 15 min Radarluecke muss dieselbe Distanz zulaessig sein, die bei 5 min unzulaessig ist."""
    trk = _trk("A", 0.0, 0.0, vx=60.0, vy=0.0)
    det = _det(0, 14.0, 0.0)  # 14 km entfernt
    ok5, _ = passes_physical_gate(trk, det, dt_minutes=5.0, max_speed_kmh=60.0)
    ok15, _ = passes_physical_gate(trk, det, dt_minutes=15.0, max_speed_kmh=60.0)
    assert not ok5, "14 km in 5 min bei 60 km/h Cap muessen abgelehnt werden"
    assert ok15, "14 km in 15 min bei 60 km/h Cap muessen zulaessig sein"


def test_search_ellipse_is_narrower_across_motion():
    """Quer zur Bewegung muss das Gate deutlich enger sein als laengs."""
    trk = _trk("A", 0.0, 0.0, vx=100.0, vy=0.0)  # bewegt sich nach +x
    along = _det(0, 8.0, 0.0)
    across = _det(1, 0.0, 8.0)
    ok_along, _ = passes_physical_gate(trk, along, 5.0, 150.0)
    ok_across, reason = passes_physical_gate(trk, across, 5.0, 150.0)
    assert ok_along, "Bewegung laengs des Vektors muss zulaessig sein"
    assert not ok_across, f"Gleiche Distanz quer zur Bewegung muss abgelehnt werden ({reason})"


def test_predict_uses_actual_dt():
    trk = _trk("A", 0.0, 0.0, vx=60.0, vy=0.0)
    assert predict_track_state(trk, 5.0)[0] == pytest.approx(5.0)
    assert predict_track_state(trk, 10.0)[0] == pytest.approx(10.0)


def test_implausible_area_growth_is_gated():
    trk = _trk("A", 0.0, 0.0, area=100.0)
    det = _det(0, 0.5, 0.0, area=100000.0)  # 1000x in 5 min
    ok, reason = passes_physical_gate(trk, det, 5.0, 150.0)
    assert not ok and "area_ratio" in reason


def test_young_track_skips_direction_gate():
    """Junge Tracks haben keinen belastbaren Vektor -> Richtungsgate darf nicht greifen."""
    young = _trk("A", 0.0, 0.0, vx=50.0, vy=0.0, age=1)
    det = _det(0, -3.0, 0.0)  # entgegen der Bewegungsrichtung
    ok, _ = passes_physical_gate(young, det, 5.0, 150.0)
    assert ok, "Richtungsgate darf bei age_frames<3 nicht greifen"


def test_gated_pairs_are_infinite_in_matrix():
    trk = _trk("A", 0.0, 0.0)
    det = _det(0, 500.0, 500.0)  # weit ausserhalb
    matrix, pairs = build_cost_matrix([trk], [det], 5.0, 150.0)
    assert matrix[0][0] >= 1e6
    assert pairs[0]["gated"] is True


def test_no_match_when_all_gated():
    trk = _trk("A", 0.0, 0.0)
    det = _det(0, 500.0, 500.0)
    res = solve_global_assignment([trk], [det], 5.0, 150.0)
    assert res.matches == {}
    assert res.unmatched_detections == [0]
    assert res.unmatched_tracks == ["A"]


def test_diagnosis_payload_is_complete():
    """Kostenmatrix und Kandidatenpaare muessen exportierbar sein (Abnahmekriterium)."""
    res = solve_global_assignment([_trk("A", 0.0, 0.0)], [_det(0, 1.0, 0.0)], 5.0, 150.0)
    assert res.cost_matrix and res.candidate_pairs
    assert "components" in res.candidate_pairs[0]
    assert res.method == "hungarian"


def test_empty_inputs_are_safe():
    res = solve_global_assignment([], [], 5.0, 150.0)
    assert res.matches == {} and res.method == "empty"
