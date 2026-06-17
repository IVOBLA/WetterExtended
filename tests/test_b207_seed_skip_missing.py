"""B207: _neighbor_motion_seed ignoriert verschwundene Zellen (missing != 0)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _seed_fn():
    ot = pytest.importorskip("object_tracking")
    return ot._neighbor_motion_seed


def test_missing_neighbor_excluded():
    # Bewegter Nachbar, aber missing=1 → darf NICHT seeden.
    seed = _seed_fn()
    snap = {"c0": {"x": 101.0, "y": 101.0, "vx": 5.0, "vy": 5.0, "missing": 1}}
    assert seed(100.0, 100.0, snap) == (0.0, 0.0)


def test_active_neighbor_included():
    # missing=0 → wird berücksichtigt.
    seed = _seed_fn()
    snap = {"c0": {"x": 101.0, "y": 101.0, "vx": 5.0, "vy": 5.0, "missing": 0}}
    vx, vy = seed(100.0, 100.0, snap)
    assert abs(vx - 5.0) < 1e-6 and abs(vy - 5.0) < 1e-6


def test_mixed_only_active_counts():
    # Aktiver (2,2) + verschwundener (10,10) → nur der aktive zählt.
    seed = _seed_fn()
    snap = {
        "c0": {"x": 101.0, "y": 101.0, "vx": 2.0, "vy": 2.0, "missing": 0},
        "c1": {"x": 102.0, "y": 102.0, "vx": 10.0, "vy": 10.0, "missing": 3},
    }
    vx, vy = seed(100.0, 100.0, snap)
    assert abs(vx - 2.0) < 1e-6 and abs(vy - 2.0) < 1e-6


def test_no_missing_key_still_counts():
    # Rückwärtskompatibilität: Snapshot ohne missing-Schlüssel → Default 0 → zählt.
    seed = _seed_fn()
    snap = {"c0": {"x": 101.0, "y": 101.0, "vx": 3.0, "vy": 1.0}}
    vx, vy = seed(100.0, 100.0, snap)
    assert abs(vx - 3.0) < 1e-6 and abs(vy - 1.0) < 1e-6
