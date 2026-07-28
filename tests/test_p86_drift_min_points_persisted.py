"""P86 — drift_status.json muss die effektive min_points-Schwelle je Horizont
persistieren, damit AC-042/043 (Richtungs-Drift-Alarm) self-contained und
divergenzfrei geprueft werden koennen. Additive Ergaenzung, keine Semantikaenderung.
"""
import drift_detector


def _synthetic_record():
    return {
        "timestamp": "2026-07-28T12:00:00Z",
        "direction_stats_by_horizon": {
            "5": {"p90_direction_error_deg": 120.0, "median_direction_error_deg": 30.0, "count": 25},
        },
        "speed_stats_by_horizon": {
            "5": {"p90_speed_error_kmh": 40.0, "median_speed_error_kmh": 5.0, "count": 25},
        },
    }


def test_min_points_persisted_dir_and_speed(monkeypatch, tmp_path):
    eval_dir = tmp_path / "evaluation"
    eval_dir.mkdir(parents=True)
    monkeypatch.setattr(drift_detector, "_read_history", lambda: [_synthetic_record()])
    monkeypatch.setattr(drift_detector, "_EVAL_DIR", str(eval_dir))
    monkeypatch.setattr(drift_detector, "_STATUS_FILE", str(eval_dir / "drift_status.json"))

    res = drift_detector.check_drift()

    expected = drift_detector._runtime_int(
        "DRIFT_DIRECTION_SPEED_MIN_POINTS", drift_detector.DRIFT_DIRECTION_SPEED_MIN_POINTS)

    dbh = res["direction_drift_by_horizon"]
    assert dbh, "direction_drift_by_horizon leer — Testrecord nicht erkannt"
    for v in dbh.values():
        assert v.get("min_points") == expected
        assert "threshold_deg" in v and "samples" in v and "p90_deg" in v

    sbh = res["speed_drift_by_horizon"]
    assert sbh, "speed_drift_by_horizon leer"
    for v in sbh.values():
        assert v.get("min_points") == expected
