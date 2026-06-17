"""B172: Bewegungs-Seed für neu entstandene Zellen (_neighbor_motion_seed)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _seed_fn():
    ot = pytest.importorskip("object_tracking")
    return ot._neighbor_motion_seed


def _snap(entries):
    """entries: Liste von (x, y, vx, vy) → previous_snapshot-Dict."""
    return {f"c{i}": {"x": x, "y": y, "vx": vx, "vy": vy}
            for i, (x, y, vx, vy) in enumerate(entries)}


def test_seed_from_moving_neighbors_is_mean():
    seed = _seed_fn()
    # zwei bewegte Nachbarn dicht bei (100,100): (2,1) und (4,3) → Mittel (3,2)
    snap = _snap([(105.0, 105.0, 2.0, 1.0), (98.0, 102.0, 4.0, 3.0)])
    vx, vy = seed(100.0, 100.0, snap)
    assert abs(vx - 3.0) < 1e-6
    assert abs(vy - 2.0) < 1e-6


def test_seed_empty_snapshot_is_zero():
    seed = _seed_fn()
    assert seed(100.0, 100.0, {}) == (0.0, 0.0)


def test_seed_ignores_far_neighbors():
    seed = _seed_fn()
    # Nachbar 250 px entfernt (>> 90 px Radius bei 30 km/UF=3) → kein Beitrag
    snap = _snap([(100.0, 350.0, 5.0, 5.0)])
    assert seed(100.0, 100.0, snap) == (0.0, 0.0)


def test_seed_ignores_resting_neighbors():
    seed = _seed_fn()
    snap = _snap([(101.0, 101.0, 0.0, 0.0), (102.0, 102.0, 0.0, 0.0)])
    assert seed(100.0, 100.0, snap) == (0.0, 0.0)
