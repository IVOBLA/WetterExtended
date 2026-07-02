from datetime import datetime, timedelta

import accuracy_tracker


def test_target_frame_search_covers_half_arso_frame_interval(monkeypatch):
    target = datetime(2026, 6, 20, 10, 10, 0)
    late_frame = target + timedelta(seconds=120)
    by_ts = {late_frame: "late.json"}

    monkeypatch.setattr(accuracy_tracker, "VERIFICATION_TIME_TOLERANCE_S", 90)

    path, delta_min, reason = accuracy_tracker._find_target_frame(by_ts, target, 90)
    assert path == "late.json"
    assert delta_min == 2.0
    assert reason is None


def test_nearest_frame_within_tolerance_returns_delta():
    """Zielzeit 00:10, vorhandener Frame 00:15 bei 5-Min-Kadenz wird akzeptiert,
    target_frame_delta_min wird korrekt berechnet.
    """
    from accuracy_tracker import _find_target_frame
    by_ts = {datetime(2026, 7, 1, 0, 15): "frame_0015.png"}
    path, delta_min, reason = _find_target_frame(by_ts, datetime(2026, 7, 1, 0, 10), time_tol_s=150)
    assert path == "frame_0015.png"
    assert delta_min == 5.0
    assert reason is None


def test_frame_outside_tolerance_classified_correctly():
    from accuracy_tracker import _find_target_frame
    by_ts = {datetime(2026, 7, 1, 0, 15): "frame_0015.png"}
    path, delta_min, reason = _find_target_frame(by_ts, datetime(2026, 7, 1, 2, 0), time_tol_s=150)
    assert path is None
    assert delta_min is None
    assert reason == "missing_due_to_ingest_gap"


def test_empty_frame_dict_is_ingest_gap():
    from accuracy_tracker import _find_target_frame
    path, delta_min, reason = _find_target_frame({}, datetime(2026, 7, 1, 0, 10), time_tol_s=150)
    assert path is None
    assert delta_min is None
    assert reason == "missing_due_to_ingest_gap"


def test_future_target_not_available():
    from accuracy_tracker import _find_target_frame
    future = datetime.utcnow() + timedelta(hours=2)
    path, delta_min, reason = _find_target_frame({}, future, time_tol_s=150)
    assert path is None
    assert delta_min is None
    assert reason in ("missing_due_to_future_not_available", "missing_due_to_ingest_gap")
