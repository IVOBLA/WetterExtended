"""B260: _effective_target_tolerance_s ist adaptiv an gemessene Radar-Kadenz."""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from accuracy_tracker import _effective_target_tolerance_s, _find_target_frame


def _make_by_ts(start: datetime, interval_min: float, count: int) -> dict:
    return {
        start + timedelta(minutes=i * interval_min): f"dummy_{i}.json"
        for i in range(count)
    }


def test_5min_kadenz_ergibt_mindestens_150s():
    by_ts = _make_by_ts(datetime(2026, 6, 28, 7, 0), 5.0, 10)
    tol = _effective_target_tolerance_s(90, by_ts)
    assert tol >= 150, f"Erwartet ≥150s bei 5-min Kadenz, erhalten {tol}s"


def test_15min_kadenz_ergibt_mindestens_450s():
    by_ts = _make_by_ts(datetime(2026, 6, 28, 0, 0), 15.0, 8)
    tol = _effective_target_tolerance_s(90, by_ts)
    assert tol >= 450, f"Erwartet ≥450s bei 15-min Kadenz, erhalten {tol}s"


def test_ohne_by_ts_fallback_auf_nominal():
    tol = _effective_target_tolerance_s(90, None)
    assert tol == 150  # max(90, 150)


def test_config_min_wird_nie_unterschritten():
    """time_tol_s-Untergrenze ist immer gewahrt."""
    by_ts = _make_by_ts(datetime(2026, 6, 28, 6, 0), 2.0, 6)  # 2-min Kadenz → 60s Halb
    tol = _effective_target_tolerance_s(90, by_ts)
    assert tol >= 90


def test_find_target_frame_findet_frame_bei_15min_kadenz():
    """_find_target_frame findet einen Frame bei 15-min Kadenz und h=10-Forecast.
    B289: Rueckgabe ist seit B278 ein 3-Tupel (pfad, delta_min, missing_reason)."""
    base = datetime(2026, 6, 29, 1, 0)
    # Frames alle 15 Minuten
    by_ts = {base + timedelta(minutes=i * 15): f"frame_{i}.json" for i in range(4)}
    target = base + timedelta(minutes=10)  # h10-Forecast zwischen zwei Frames
    path, delta_min, missing_reason = _find_target_frame(by_ts, target, 90)
    assert path is not None, (
        "h10-Forecast bei 15-min Kadenz darf nicht als no_target_frame gezählt werden"
    )
    assert missing_reason is None


def test_regression_5min_kadenz_unveraendert():
    """B260 darf 5-min-Kadenz-Verhalten nicht verschlechtern.
    B289: Rueckgabe ist seit B278 ein 3-Tupel (pfad, delta_min, missing_reason)."""
    base = datetime(2026, 6, 28, 12, 0)
    by_ts = {base + timedelta(minutes=i * 5): f"f_{i}.json" for i in range(12)}
    # Ziel exakt auf einen vorhandenen Frame
    path, delta_min, missing_reason = _find_target_frame(by_ts, base + timedelta(minutes=10), 90)
    assert path == by_ts[base + timedelta(minutes=10)]
    assert delta_min == 0.0
    assert missing_reason is None
