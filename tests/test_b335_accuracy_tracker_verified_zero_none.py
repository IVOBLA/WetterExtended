import json
from datetime import datetime, timedelta


def _import_accuracy_tracker(monkeypatch, tmp_path):
    # B359: siehe test_b296_nn_threshold_and_median.py — kein sys.modules.pop
    # mehr, direktes Patchen des bereits importierten Moduls.
    import accuracy_tracker as at
    monkeypatch.setattr(at, "debug_log", lambda *args, **kwargs: None, raising=False)
    ev = tmp_path / "evaluation"
    ev.mkdir(exist_ok=True)
    monkeypatch.setattr(at, "EVAL_DIR", str(ev), raising=False)
    monkeypatch.setattr(at, "DETAILS_FILE", str(ev / "forecast_error_details.jsonl"), raising=False)
    monkeypatch.setattr(at, "HISTORY_FILE", str(ev / "accuracy_history.jsonl"), raising=False)
    return at


def _write_objects(directory, ts, objects):
    path = directory / f"{ts:%Y-%m-%d_%H-%M-%S}.json"
    path.write_text(json.dumps(objects), encoding="utf-8")
    return path


def test_evaluate_for_horizon_returns_none_metrics_when_verified_zero(monkeypatch, tmp_path):
    """B335: n_total > 0 aber verified == 0 (nur no_target_frame) darf NICHT
    mae_km/rmse_km/mae_px/rmse_x_px/rmse_y_px == 0.0 liefern, sondern None."""
    accuracy_tracker = _import_accuracy_tracker(monkeypatch, tmp_path)

    obj_dir = tmp_path / "objects"
    obj_dir.mkdir()
    t0 = datetime(2026, 6, 18, 12, 0, 0)
    # Nur EIN Frame vorhanden -> fuer horizon=60 existiert kein Ziel-Frame
    # (target_ts liegt weit ausserhalb der Toleranz von 90s) => no_target_frame,
    # n_total > 0, verified == 0.
    _write_objects(
        obj_dir,
        t0,
        [{
            "id": "WX-TEST-1",
            "cell_id": "WX-TEST-1",
            "x": 10.0,
            "y": 20.0,
            "lat": 46.70,
            "lon": 14.10,
            "forecast_x_60": 12.0,
            "forecast_y_60": 22.0,
            "forecast_lat_60": 46.71,
            "forecast_lon_60": 14.11,
            "forecast_mode": "kinematic",
            "forecast_mode_60": "kinematic",
            "kinematic_source": "object-summary",
            "kinematic_source_60": "ewma_3f",
        }],
    )

    monkeypatch.setitem(accuracy_tracker.SAVE_PATHS, "objects", str(obj_dir))

    result = accuracy_tracker.evaluate_for_horizon(60, since_hours=24)

    assert result["samples"] > 0, "Testfall muss n_total > 0 erzeugen (Voraussetzung fuer den Bug)"
    assert result["verified"] == 0
    assert result["mae_km"] is None, f"mae_km muss None sein bei verified=0, war {result['mae_km']}"
    assert result["rmse_km"] is None
    assert result["mae_px"] is None
    assert result["rmse_x_px"] is None
    assert result["rmse_y_px"] is None


def test_evaluate_for_horizon_still_computes_metrics_when_verified_positive(monkeypatch, tmp_path):
    """Regressionsschutz: bei verified > 0 muessen die Kennzahlen weiterhin normal
    berechnet werden (kein Nebeneffekt durch die Entfernung von eval_n)."""
    accuracy_tracker = _import_accuracy_tracker(monkeypatch, tmp_path)

    obj_dir = tmp_path / "objects"
    obj_dir.mkdir()
    t0 = datetime(2026, 6, 18, 12, 0, 0)
    _write_objects(
        obj_dir,
        t0,
        [{
            "id": "WX-TEST-1", "cell_id": "WX-TEST-1", "x": 10.0, "y": 20.0, "lat": 46.70, "lon": 14.10,
            "forecast_x_30": 10.0, "forecast_y_30": 20.0,
            "forecast_lat_30": 46.70, "forecast_lon_30": 14.10,
            "forecast_mode_30": "kinematic", "kinematic_source_30": "ewma_3f",
        }],
    )
    _write_objects(obj_dir, t0 + timedelta(minutes=30),
                   [{"id": "WX-TEST-1", "cell_id": "WX-TEST-1", "x": 10.0, "y": 20.0, "lat": 46.70, "lon": 14.10}])
    monkeypatch.setitem(accuracy_tracker.SAVE_PATHS, "objects", str(obj_dir))

    result = accuracy_tracker.evaluate_for_horizon(30, since_hours=24)

    assert result["verified"] == 1
    assert result["mae_km"] == 0.0
    assert result["rmse_km"] == 0.0
