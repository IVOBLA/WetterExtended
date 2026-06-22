# tests/test_b231_min_interval_disp.py
"""B231 — Mindest-Displacement-Filter fuer die EWMA-Bewegungsableitung.
Default 0.0 = regressionsneutral; Schwelle > 0 trennt Rauschen von Bewegung."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import prediction as p


def test_default_is_regression_neutral():
    from config import KINEMATIC_MIN_INTERVAL_DISP_PX
    assert KINEMATIC_MIN_INTERVAL_DISP_PX == 0.0


def test_threshold_zero_always_ok():
    assert p._interval_disp_ok(0.0, 0.0, 0.0) is True
    assert p._interval_disp_ok(0.1, 0.1, 0.0) is True


def test_subthreshold_interval_rejected():
    assert p._interval_disp_ok(0.1, 0.1, 2.0) is False   # disp ~0.14
    assert p._interval_disp_ok(1.0, 1.0, 2.0) is False   # disp ~1.41


def test_real_movement_interval_accepted():
    assert p._interval_disp_ok(3.0, 4.0, 2.0) is True    # disp 5.0
    assert p._interval_disp_ok(2.0, 0.0, 2.0) is True    # disp 2.0 == Schwelle
