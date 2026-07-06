"""
B302: Nearest-Target-Frame-Toleranz in der Closed-Loop-Verifikation.

Verifiziert, dass bei gröberem Radar-Takt (15 min) die Kurzhorizonte 10/20/40 min
gegen den nächstgelegenen real vorhandenen Radar-Frame gematcht werden, statt als
no_target_frame verworfen zu werden. Echte Lücken bleiben no_target_frame.
"""
from datetime import datetime, timedelta

import accuracy_tracker as at


def _by_ts(base, minutes_list):
    """{datetime: pfad} für Frames zu base+minutes."""
    return {base + timedelta(minutes=m): f"frame_{m}.json" for m in minutes_list}


def test_nearest_frame_found_for_h10_at_15min_cadence():
    # 15-min-Takt: Frames bei +0, +15, +30
    base = datetime(2026, 7, 5, 0, 0, 0)
    by_ts = _by_ts(base, [0, 15, 30])
    # Horizont 10 min: Ziel = +10, nächster Frame = +15 (Δ 5 min = 300 s)
    target_ts = base + timedelta(minutes=10)
    path, delta_min, reason = at._find_target_frame(by_ts, target_ts, at.VERIFICATION_TIME_TOLERANCE_S)
    assert path == "frame_15.json", "h10 muss bei 15-min-Takt den +15-Frame matchen"


def test_nearest_frame_found_for_h20_at_15min_cadence():
    base = datetime(2026, 7, 5, 0, 0, 0)
    by_ts = _by_ts(base, [0, 15, 30])
    # Ziel = +20, nächster Frame = +15 (Δ 5 min) statt +30 (Δ 10 min)
    target_ts = base + timedelta(minutes=20)
    path, delta_min, reason = at._find_target_frame(by_ts, target_ts, at.VERIFICATION_TIME_TOLERANCE_S)
    assert path == "frame_15.json"


def test_large_gap_still_no_target_frame():
    # Regression: echte Lücke (kein Frame < 7,5 min) darf NICHT gematcht werden.
    base = datetime(2026, 7, 5, 0, 0, 0)
    by_ts = _by_ts(base, [0, 40])
    target_ts = base + timedelta(minutes=10)  # nächster Frame +0 (Δ 10 min) / +40 (Δ 30 min)
    path, delta_min, reason = at._find_target_frame(by_ts, target_ts, at.VERIFICATION_TIME_TOLERANCE_S)
    assert path is None, "Lücke > 7,5 min muss weiterhin no_target_frame ergeben"


def test_effective_tolerance_at_least_nearest_default():
    # Effektive Toleranz muss mindestens die Nearest-Frame-Toleranz sein.
    eff = at._effective_target_tolerance_s(at.VERIFICATION_TIME_TOLERANCE_S)
    assert eff >= at.VERIFICATION_NEAREST_FRAME_TOLERANCE_S


def test_exact_match_preferred_over_nearest():
    # Ist ein Frame nahe am Ziel, wird er dem weiter entfernten vorgezogen.
    base = datetime(2026, 7, 5, 0, 0, 0)
    by_ts = _by_ts(base, [9, 15])  # +9 (Δ 1 min) vs +15 (Δ 5 min) für Ziel +10
    target_ts = base + timedelta(minutes=10)
    path, delta_min, reason = at._find_target_frame(by_ts, target_ts, at.VERIFICATION_TIME_TOLERANCE_S)
    assert path == "frame_9.json", "nächster Frame (+9) muss gewinnen"
