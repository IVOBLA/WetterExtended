"""B400: Die Kostenschwelle muss erreichbar sein und Hungarian darf unmatched wählen."""
import pytest

from tracking.association import (
    DetectionCandidate,
    TrackCandidate,
    _DEFAULTS,
    solve_global_assignment,
)


def _trk(tid, x, y, area=1000.0, core=0.3, age=5):
    return TrackCandidate(track_id=tid, pred_x_km=x, pred_y_km=y, vx_kmh=0.0, vy_kmh=0.0,
                          area_px=area, core_ratio=core, age_frames=age)


def _det(i, x, y, area=1000.0, core=0.3):
    return DetectionCandidate(index=i, x_km=x, y_km=y, area_px=area, core_ratio=core)


def test_max_cost_is_reachable():
    """KERNREGRESSION: die Schwelle muss unter der maximal moeglichen Paarung liegen."""
    weights = sum(_DEFAULTS[k] for k in
                  ("ASSOC_W_POS", "ASSOC_W_IOU", "ASSOC_W_AREA",
                   "ASSOC_W_DIR", "ASSOC_W_CORE", "ASSOC_W_AGE"))
    assert weights == pytest.approx(1.0), "Testannahme: Gewichte summieren auf 1.00"
    assert _DEFAULTS["ASSOC_MAX_COST"] < weights, (
        f"ASSOC_MAX_COST={_DEFAULTS['ASSOC_MAX_COST']} ist bei max. Kosten "
        f"{weights} unerreichbar — die Schwelle waere toter Code"
    )


def test_unmatched_cost_above_max_cost():
    """Ein Paar unterhalb der Schwelle muss der Nicht-Zuordnung vorgezogen werden."""
    assert _DEFAULTS["ASSOC_UNMATCHED_COST"] > _DEFAULTS["ASSOC_MAX_COST"]


def test_good_pair_is_not_displaced_by_bad_one():
    """KERNFALL: ein schlechtes Paar darf ein gutes nicht verdraengen.

    Ohne Dummy-Spalte minimiert Hungarian die Summe und weist D1 dem schlechten
    Track zu, um D2 ein etwas besseres zu lassen.
    """
    t1 = _trk("T1", 0.0, 0.0)
    t2 = _trk("T2", 40.0, 0.0)
    d1 = _det(0, 0.5, 0.0)
    d2 = _det(1, 2.0, 0.0)
    res = solve_global_assignment([t1, t2], [d1, d2], dt_minutes=5.0, max_speed_kmh=150.0)
    assert res.matches.get(0) == "T1", (
        f"Bestes Paar wurde verdraengt: matches={res.matches}"
    )
    assert 1 in res.unmatched_detections, "D2 haette unmatched bleiben muessen"


def test_solver_may_choose_no_assignment():
    """Eine Detektion ohne akzeptablen Track bleibt unmatched statt falsch zugeordnet."""
    t1 = _trk("T1", 0.0, 0.0, area=1000.0, core=0.9)
    d1 = _det(0, 12.0, 0.0, area=9000.0, core=0.0)
    res = solve_global_assignment([t1], [d1], dt_minutes=5.0, max_speed_kmh=150.0)
    if res.matches:
        pair = res.candidate_pairs[0]
        assert pair["cost"] <= _DEFAULTS["ASSOC_MAX_COST"], (
            f"Paar mit cost={pair['cost']} wurde trotz Schwelle akzeptiert"
        )
    else:
        assert 0 in res.unmatched_detections
        assert any(r["reason"] in ("no_acceptable_track", "cost_above_max")
                   for r in res.rejected_matches)


def test_rejection_reason_is_reported():
    """Die Diagnose muss die bewusste Nicht-Zuordnung ausweisen."""
    t1 = _trk("T1", 0.0, 0.0, core=0.9, area=1000.0)
    d1 = _det(0, 13.0, 0.0, area=9500.0, core=0.0)
    res = solve_global_assignment([t1], [d1], dt_minutes=5.0, max_speed_kmh=150.0)
    if not res.matches:
        reasons = {r["reason"] for r in res.rejected_matches}
        assert reasons & {"no_acceptable_track", "cost_above_max", "gated"}


def test_excellent_pair_still_matches():
    """Regression: gute Paare muessen weiterhin zugeordnet werden."""
    res = solve_global_assignment([_trk("T1", 0.0, 0.0)], [_det(0, 0.3, 0.0)], 5.0, 150.0)
    assert res.matches.get(0) == "T1"


def test_all_gated_yields_no_match():
    res = solve_global_assignment([_trk("T1", 0.0, 0.0)], [_det(0, 500.0, 500.0)], 5.0, 150.0)
    assert res.matches == {}
    assert res.unmatched_detections == [0]
    assert res.unmatched_tracks == ["T1"]


def test_more_detections_than_tracks():
    """Ueberzaehlige Detektionen muessen sauber unmatched bleiben."""
    res = solve_global_assignment(
        [_trk("T1", 0.0, 0.0)], [_det(0, 0.3, 0.0), _det(1, 0.6, 0.0)], 5.0, 150.0)
    assert len(res.matches) == 1
    assert len(res.unmatched_detections) == 1


def test_more_tracks_than_detections():
    res = solve_global_assignment(
        [_trk("T1", 0.0, 0.0), _trk("T2", 1.0, 0.0)], [_det(0, 0.3, 0.0)], 5.0, 150.0)
    assert len(res.matches) == 1
    assert len(res.unmatched_tracks) == 1


def test_diagnosis_still_complete():
    res = solve_global_assignment([_trk("T1", 0.0, 0.0)], [_det(0, 0.3, 0.0)], 5.0, 150.0)
    assert res.cost_matrix and res.candidate_pairs and res.method == "hungarian"


def test_empty_inputs_are_safe():
    res = solve_global_assignment([], [], 5.0, 150.0)
    assert res.matches == {} and res.method == "empty"
