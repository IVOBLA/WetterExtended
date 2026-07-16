from datetime import datetime, timedelta, timezone
import random

import hydro_flood_ml as h


def _label(values):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [{"measured_at": (start + timedelta(minutes=30 * i)).isoformat(), "q_m3s": q}
            for i, q in enumerate(values[1:], 1)]
    return h._label_from_future({"measured_at": start.isoformat(), "q_m3s": values[0]}, rows, None)


def test_rising_falling_and_peak_targets():
    rising = _label([5, 9])
    falling = _label([9, 5])
    peak = _label([5, 12, 6])
    assert (rising["target_q_delta_m3s"], rising["target_window_q_max_m3s"]) == (4.0, 9.0)
    assert (falling["target_q_delta_m3s"], falling["target_window_q_max_m3s"], falling["target_q_change_end_m3s"]) == (0.0, 9.0, -4.0)
    assert (peak["target_q_delta_m3s"], peak["target_q_change_end_m3s"]) == (7.0, 1.0)
    assert all(x["target_q_max_m3s"] == x["target_window_q_max_m3s"] for x in (rising, falling, peak))


def test_delta_is_non_negative_for_random_series():
    rng = random.Random(418)
    for _ in range(500):
        label = _label([rng.uniform(0, 100) for _ in range(rng.randint(2, 8))])
        assert label["target_q_delta_m3s"] >= 0


def test_missing_window_remains_missing():
    assert h._label_from_future({"measured_at": "2026-01-01T00:00:00Z", "q_m3s": 5}, [], None) == {"target_missing": True}


def test_recession_target_is_not_used_for_training():
    import inspect
    assert "target_q_change_end_m3s" not in inspect.getsource(h._train_model_unlocked)
