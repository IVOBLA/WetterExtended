from datetime import datetime, timedelta

import accuracy_tracker


def test_target_frame_search_covers_half_arso_frame_interval(monkeypatch):
    target = datetime(2026, 6, 20, 10, 10, 0)
    late_frame = target + timedelta(seconds=120)
    by_ts = {late_frame: "late.json"}

    monkeypatch.setattr(accuracy_tracker, "VERIFICATION_TIME_TOLERANCE_S", 90)

    assert accuracy_tracker._find_target_frame(by_ts, target, 90) == "late.json"
