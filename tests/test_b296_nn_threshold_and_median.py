"""B296: NN-Akzeptanzschwellen h30/h40/h60 verschärft + median_km-Kennzahl."""
import json
from datetime import datetime, timedelta


def _import_accuracy_tracker(monkeypatch, tmp_path):
    # B359: KEIN sys.modules.pop mehr — das erzeugt bei jedem Aufruf ein neues
    # Modul-Objekt und verwaist app.py's bereits gebundene Referenzen
    # (evaluate_all/load_history), die weiterhin auf das ALTE Modul-Objekt
    # zeigen. Stattdessen wird das bereits importierte, session-weit EINE
    # accuracy_tracker-Modul direkt gepatcht (monkeypatch reverted automatisch
    # nach dem Test) — so bleiben alle Referenzen im Prozess konsistent.
    import accuracy_tracker as at
    monkeypatch.setattr(at, "debug_log", lambda *a, **k: None, raising=False)
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


def test_thresholds_tightened_below_previous_values():
    from config import VERIFICATION_NN_MAX_MATCH_KM_BY_HORIZON as T
    assert T["30"] < 8.0
    assert T["40"] < 9.0
    assert T["60"] < 10.0
    # Muss weiterhin monoton mit dem Horizont steigen (test_b213-Invariante).
    assert T["10"] < T["60"]


def test_outlier_like_wx20260703_0002_now_rejected(monkeypatch, tmp_path):
    """Reproduziert den h40-Ausreisser aus dem Export (7.30 km) — muss jetzt
    als nn_rejected verworfen werden statt die MAE zu verzerren."""
    at = _import_accuracy_tracker(monkeypatch, tmp_path)
    obj_dir = tmp_path / "objects"
    obj_dir.mkdir()
    t0 = datetime(2026, 7, 3, 17, 25, 0)
    _write_objects(obj_dir, t0, [{
        "id": "WX-20260703-0002", "cell_id": "WX-20260703-0002",
        "x": 10.0, "y": 10.0, "lat": 46.720945984126985, "lon": 14.907768312857144,
        "forecast_x_40": 10.0, "forecast_y_40": 10.0,
        "forecast_lat_40": 46.720945984126985, "forecast_lon_40": 14.907768312857144,
    }])
    # Ziel-Frame: andere ID (Lineage verloren, wie im echten Export) ~7.3 km entfernt.
    _write_objects(obj_dir, t0 + timedelta(minutes=40), [{
        "id": "OTHER-ID", "cell_id": "OTHER-ID",
        "lat": 46.72211003331374, "lon": 15.003570061728396,
    }])
    monkeypatch.setitem(at.SAVE_PATHS, "objects", str(obj_dir))

    result = at.evaluate_for_horizon(40, since_hours=24)

    assert result["nn_rejected"] == 1
    assert result["verified"] == 0


def test_median_km_present_and_robust(monkeypatch, tmp_path):
    at = _import_accuracy_tracker(monkeypatch, tmp_path)
    obj_dir = tmp_path / "objects"
    obj_dir.mkdir()
    t0 = datetime(2026, 6, 18, 12, 0, 0)
    _write_objects(obj_dir, t0, [
        {"id": "A", "cell_id": "A", "x": 0.0, "y": 0.0, "lat": 46.70, "lon": 14.10,
         "forecast_x_10": 0.0, "forecast_y_10": 0.0, "forecast_lat_10": 46.70, "forecast_lon_10": 14.10},
        {"id": "B", "cell_id": "B", "x": 0.0, "y": 0.0, "lat": 46.80, "lon": 14.20,
         "forecast_x_10": 0.0, "forecast_y_10": 0.0, "forecast_lat_10": 46.80, "forecast_lon_10": 14.20},
    ])
    _write_objects(obj_dir, t0 + timedelta(minutes=10), [
        {"id": "A", "cell_id": "A", "lat": 46.70, "lon": 14.10},
        {"id": "B", "cell_id": "B", "lat": 46.80, "lon": 14.20},
    ])
    monkeypatch.setitem(at.SAVE_PATHS, "objects", str(obj_dir))

    result = at.evaluate_for_horizon(10, since_hours=24)

    assert "median_km" in result
    assert result["median_km"] is not None
    assert result["median_km"] <= result["mae_km"] + 1e-6
