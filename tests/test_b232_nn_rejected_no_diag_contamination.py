# tests/test_b232_nn_rejected_no_diag_contamination.py
"""B232 — nn_rejected-Detailzeilen tragen keine forecast_error_km und werden von
der Fehler-Diagnose als ungueltig ('missing_error_metric') ausgeschlossen."""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import accuracy_tracker as at
import forecast_error_diagnosis as fed


def test_detail_record_nn_rejected_has_no_error_metric():
    rec = at._detail_record({}, datetime(2026, 6, 21, 23, 50, 0),
                            datetime(2026, 6, 22, 0, 0, 0), 10,
                            None, None, "nn_rejected", False, False, 10)
    assert rec["forecast_error_km"] is None
    assert rec["match_distance_km"] is None
    assert rec.get("match_type") == "nn_rejected"


def _row(error_km, *, missed=False):
    return {
        "forecast_created_at_utc": "2026-06-22T10:00:00Z",
        "target_timestamp_utc": "2026-06-22T10:10:00Z",
        "verified_at_utc": "2026-06-22T10:10:30Z",
        "horizon_min": 10,
        "match_type": "nn_rejected",
        "missed": missed,
        "no_target_frame": False,
        "forecast_error_km": error_km,
    }


def test_diagnosis_excludes_nn_rejected_without_error():
    now = datetime(2026, 6, 22, 10, 11, tzinfo=timezone.utc)
    ok, reason = fed.is_valid_forecast_error_detail(_row(None), now_utc=now)
    assert ok is False
    assert reason == "rejected_match"


def test_diagnosis_excludes_production_nn_rejected_missed_row():
    now = datetime(2026, 6, 22, 10, 11, tzinfo=timezone.utc)
    ok, reason = fed.is_valid_forecast_error_detail(_row(None, missed=True), now_utc=now)
    assert ok is False
    assert reason == "rejected_match"


def test_diagnosis_excludes_nn_rejected_even_with_error():
    # Regressionsschutz: alte Details mit Distanz duerfen MAE/Worst-Listen nicht kontaminieren.
    now = datetime(2026, 6, 22, 10, 11, tzinfo=timezone.utc)
    ok, reason = fed.is_valid_forecast_error_detail(_row(5.0), now_utc=now)
    assert ok is False
    assert reason == "rejected_match"


def test_filter_drops_rejected_keeps_valid():
    now = datetime(2026, 6, 22, 10, 11, tzinfo=timezone.utc)
    valid_row = _row(5.0)
    valid_row["match_type"] = "id"
    valid, _counts, _examples = fed._filter_valid_details(
        [_row(None, missed=True), _row(5.0), valid_row], now_utc=now
    )
    assert len(valid) == 1
    assert valid[0]["forecast_error_km"] == 5.0
    assert valid[0]["match_type"] == "id"
