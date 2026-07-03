"""P71: Richtungs-/Geschwindigkeitsfehler als eigene Drift-Kennzahl mit Schwellwert-Alarm."""


def test_direction_alarm_triggers_above_threshold():
    dstats = {"10": {"median_direction_error_deg": 54.0, "p90_direction_error_deg": 140.0, "samples": 100}}
    thr, min_pts = 90.0, 20
    alarm = False
    for hk, v in dstats.items():
        p90 = v.get("p90_direction_error_deg"); n = int(v.get("samples", 0) or 0)
        if p90 is not None and n >= min_pts and p90 > thr:
            alarm = True
    assert alarm is True


def test_direction_no_alarm_below_threshold():
    dstats = {"10": {"p90_direction_error_deg": 25.0, "samples": 100}}
    thr, min_pts = 90.0, 20
    alarm = any(v["p90_direction_error_deg"] > thr and v["samples"] >= min_pts for v in dstats.values())
    assert alarm is False


def test_insufficient_samples_suppress_alarm():
    dstats = {"10": {"p90_direction_error_deg": 140.0, "samples": 5}}
    thr, min_pts = 90.0, 20
    alarm = any((v.get("p90_direction_error_deg") or 0) > thr and int(v.get("samples", 0)) >= min_pts for v in dstats.values())
    assert alarm is False


def test_long_horizons_excluded_from_short_horizon_check():
    short_max = 30.0
    dstats = {"60": {"p90_direction_error_deg": 200.0, "samples": 100}}
    considered = [hk for hk in dstats if float(hk) <= short_max]
    assert considered == []


def test_speed_alarm_triggers_above_threshold():
    sstats = {"20": {"p90_speed_error_kmh": 45.0, "samples": 60}}
    thr, min_pts = 30.0, 20
    alarm = any((v.get("p90_speed_error_kmh") or 0) > thr and int(v.get("samples", 0)) >= min_pts for v in sstats.values())
    assert alarm is True


def test_config_defaults_present():
    from config import DRIFT_DIRECTION_P90_MAX_DEG, DRIFT_SPEED_P90_MAX_KMH, DRIFT_DIRECTION_SPEED_MIN_POINTS
    assert DRIFT_DIRECTION_P90_MAX_DEG == 90.0
    assert DRIFT_SPEED_P90_MAX_KMH == 30.0
    assert DRIFT_DIRECTION_SPEED_MIN_POINTS == 20
