"""C.1 — Dashboard-Forecast-Modus nutzt aktuellen ML-Blockstatus.

Statische Quellpruefung (kein Node noetig): Das Dashboard muss
ml_blocked_reason als aktuellen Produktivzustand priorisieren, damit es der
Lernfortschritt-Seite nicht widerspricht.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD = ROOT / "frontend" / "src" / "pages" / "Dashboard.jsx"
PROGRESS = ROOT / "frontend" / "src" / "pages" / "Progress.jsx"


def _src(path):
    assert path.exists(), f"{path} fehlt"
    return path.read_text(encoding="utf-8")


def _forecast_mode_block():
    src = _src(DASHBOARD)
    match = re.search(
        r"const runtimeStatus = forecastStats\?\.runtime_status \|\| \{}(?P<block>.*?)"
        r"const handleServiceClick =",
        src,
        re.S,
    )
    assert match, "Forecast-Modus-Hilfswerte fehlen oder stehen nicht vor dem Rendern"
    return match.group(0)


def test_dashboard_uses_ml_blocked_reason():
    src = _src(DASHBOARD)
    block = _forecast_mode_block()

    assert "current_runtime_mode" in src, "Dashboard wertet current_runtime_mode nicht aus"
    assert "historical_24h_usage" in src, "Dashboard trennt historische Nutzung nicht vom Runtime-Status"
    assert "value={forecastModeValue}" in src, \
        "Forecast-Modus-Card muss den berechneten, blockstatusbewussten Wert nutzen"
    assert "value={forecastStats.active_mode" not in src, \
        "Forecast-Modus-Card nutzt weiterhin direkt active_mode"


def test_dashboard_shows_fallback_when_ml_blocked():
    block = _forecast_mode_block()

    for required in (
        "mlBlocked",
        "currentRuntimeMode",
        "Fallback-Grund",
        "border-yellow",
        "📐 Aktueller Modus: Fallback aktiv",
        "Historie 24h",
    ):
        assert required in block, f"{required!r} fehlt im Forecast-Modus-Block"


def test_progress_still_uses_forecast_stats():
    src = _src(PROGRESS)

    assert "/api/forecast_stats" in src, "Progress nutzt forecast_stats nicht mehr"
    assert "ml_blocked_reason" in src, "Progress wertet ml_blocked_reason nicht mehr aus"
    assert "const mlActive" in src and "fcStats.ml_blocked_reason == null" in src, \
        "Progress muss den aktiven Modus weiterhin ueber ml_blocked_reason bestimmen"


def test_accuracy_page_shows_b277_ml_quality_fields():
    src = _src(ROOT / "frontend" / "src" / "pages" / "Accuracy.jsx")

    assert "runtime_kinematic_mae_by_horizon" in src
    assert "last_promotion" in src
    assert "promotion_decision" in src
    assert "promotion_reject_reason" in src
    assert "promotion_baseline_source" in src
    assert "Runtime-Gate / Promotion-Baseline" in src


def test_ml_quality_api_exposes_b277_fields(monkeypatch, tmp_path):
    import pytest
    flask = pytest.importorskip("flask")
    assert flask is not None
    import app as wetter_app

    eval_dir = tmp_path / "evaluation"
    model_dir = tmp_path / "models"
    eval_dir.mkdir()
    model_dir.mkdir()
    (eval_dir / "accuracy_history.jsonl").write_text(
        '{"timestamp_utc":"2026-07-02T00:00:00Z","breakdown_by_forecast_mode":{"10":{"kinematic":{"mae_km":0.7,"verified":30},"ml":{"mae_km":0.6,"verified":30}}}}\n',
        encoding="utf-8",
    )
    (model_dir / "training_meta.json").write_text(
        '{"promotion_decision":"rejected","promotion_reject_reason":"ml_mae_worse_than_runtime_kinematic_baseline","promotion_baseline_source":{"10":"runtime_accuracy_history"}}',
        encoding="utf-8",
    )
    monkeypatch.setitem(wetter_app.SAVE_PATHS, "evaluation", str(eval_dir))
    monkeypatch.setitem(wetter_app.SAVE_PATHS, "models", str(model_dir))
    monkeypatch.setitem(wetter_app.cfg.SAVE_PATHS, "evaluation", str(eval_dir))
    monkeypatch.setitem(wetter_app.cfg.SAVE_PATHS, "models", str(model_dir))
    import accuracy_tracker as _accuracy_tracker
    monkeypatch.setattr(_accuracy_tracker, "HISTORY_FILE", str(eval_dir / "accuracy_history.jsonl"))
    monkeypatch.setattr(wetter_app.runtime_config, "get", lambda key, default=None: [10] if key == "ML_FORECAST_HORIZONS_MIN" else default)

    with wetter_app.app.test_client() as client:
        resp = client.get("/api/ml_quality?hours=168")

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["runtime_kinematic_mae_by_horizon"]["10"]["kinematic_mae"] == 0.7
    assert payload["last_promotion"]["promotion_decision"] == "rejected"
    assert payload["last_promotion"]["promotion_baseline_source"]["10"] == "runtime_accuracy_history"


def test_p69_existing_quality_endpoints_expose_transparency_fields(monkeypatch, tmp_path):
    import pytest
    flask = pytest.importorskip("flask")
    assert flask is not None
    import app as wetter_app

    eval_dir = tmp_path / "evaluation"
    model_dir = tmp_path / "models"
    eval_dir.mkdir()
    model_dir.mkdir()
    (eval_dir / "accuracy_history.jsonl").write_text(
        '{"timestamp_utc":"2026-07-02T00:00:00Z","breakdown_by_forecast_mode":{"10":{"kinematic_fallback":{"mae_km":0.7,"samples":90,"verified":90},"ml":{"mae_km":0.6,"samples":10,"verified":8,"no_target_frame":2}}},"delivered_mode_counts":{"10":{"kinematic_fallback":90,"ml":10}}}\n',
        encoding="utf-8",
    )
    (model_dir / "training_meta.json").write_text(
        '{"promotion_decision":"rejected","promotion_reject_reason":"ml_mae_worse_than_runtime_kinematic_baseline","promotion_baseline_source":{"10":"runtime_accuracy_history"}}',
        encoding="utf-8",
    )
    monkeypatch.setitem(wetter_app.SAVE_PATHS, "evaluation", str(eval_dir))
    monkeypatch.setitem(wetter_app.SAVE_PATHS, "models", str(model_dir))
    monkeypatch.setitem(wetter_app.cfg.SAVE_PATHS, "evaluation", str(eval_dir))
    monkeypatch.setitem(wetter_app.cfg.SAVE_PATHS, "models", str(model_dir))
    # B290: load_history() liest aus der beim Modul-Import einmalig berechneten
    # Konstante accuracy_tracker.HISTORY_FILE, NICHT dynamisch aus SAVE_PATHS.
    # setitem auf SAVE_PATHS allein wirkt sich darauf nicht aus (etabliertes
    # Muster, siehe Test unmittelbar oberhalb in derselben Datei).
    import accuracy_tracker as _accuracy_tracker
    monkeypatch.setattr(_accuracy_tracker, "HISTORY_FILE", str(eval_dir / "accuracy_history.jsonl"))
    monkeypatch.setattr(wetter_app.runtime_config, "get", lambda key, default=None: [10] if key == "ML_FORECAST_HORIZONS_MIN" else default)

    monkeypatch.setattr(
        "prediction._ml_runtime_gate_by_horizon",
        lambda horizons: {int(h): {"reason": "shadow_mode", "allow_ml": False} for h in horizons},
        raising=False,
    )
    monkeypatch.setattr(
        "export_diagnosis.load_latest_forecast_quality_diagnosis",
        lambda save_paths=None: {"status": "ok", "bias_by_horizon": {"10": {"sample_count": 3}}},
    )

    with wetter_app.app.test_client() as client:
        ml_resp = client.get("/api/ml_quality?hours=168")
        diag_resp = client.get("/api/forecast_quality_diagnosis")

    assert ml_resp.status_code == 200
    ml_payload = ml_resp.get_json()
    assert "forecast_mode_counts" in ml_payload
    assert "ml_usage_ratio" in ml_payload
    assert "ml_gate_reasons" in ml_payload
    assert "verification_coverage_by_horizon" in ml_payload
    assert ml_payload["forecast_mode_counts"]["ml"] == 10
    assert ml_payload["ml_usage_ratio"] == 0.1
    assert ml_payload["ml_gate_reasons"] == {"10": {"reason": "shadow_mode", "allow_ml": False}}
    assert set(ml_payload["ml_gate_reasons"]["10"].keys()) == {"reason", "allow_ml"}
    assert ml_payload["verification_coverage_by_horizon"]["10"] == round(98 / 102, 4)

    assert diag_resp.status_code == 200
    assert "bias_by_horizon" in diag_resp.get_json()


def test_evaluate_for_horizon_separates_shadow_ml_from_delivered_counts(monkeypatch, tmp_path):
    import json
    import sys
    import types
    from datetime import datetime, timedelta

    sys.modules.pop("accuracy_tracker", None)
    monkeypatch.setitem(sys.modules, "debug_utils", types.SimpleNamespace(debug_log=lambda *args, **kwargs: None))
    import accuracy_tracker

    ev = tmp_path / "evaluation"
    ev.mkdir()
    monkeypatch.setattr(accuracy_tracker, "EVAL_DIR", str(ev), raising=False)
    monkeypatch.setattr(accuracy_tracker, "DETAILS_FILE", str(ev / "forecast_error_details.jsonl"), raising=False)
    monkeypatch.setattr(accuracy_tracker, "HISTORY_FILE", str(ev / "accuracy_history.jsonl"), raising=False)

    obj_dir = tmp_path / "objects"
    obj_dir.mkdir()
    t0 = datetime(2026, 6, 18, 12, 0, 0)

    def write_objects(ts, objects):
        (obj_dir / f"{ts:%Y-%m-%d_%H-%M-%S}.json").write_text(json.dumps(objects), encoding="utf-8")

    write_objects(t0, [{
        "id": "WX-B284-1", "cell_id": "WX-B284-1",
        "x": 10.0, "y": 20.0, "lat": 46.70, "lon": 14.10,
        "forecast_x_30": 10.0, "forecast_y_30": 20.0,
        "forecast_lat_30": 46.70, "forecast_lon_30": 14.10,
        "forecast_mode_30": "kinematic_fallback", "kinematic_source_30": "ewma_3f",
        "forecast_ml_lat_30": 46.70, "forecast_ml_lon_30": 14.10,
    }])
    write_objects(t0 + timedelta(minutes=30), [{
        "id": "WX-B284-1", "cell_id": "WX-B284-1",
        "x": 10.0, "y": 20.0, "lat": 46.70, "lon": 14.10,
    }])
    monkeypatch.setitem(accuracy_tracker.SAVE_PATHS, "objects", str(obj_dir))

    result = accuracy_tracker.evaluate_for_horizon(30, since_hours=24)

    assert result["by_forecast_mode"]["kinematic_fallback"]["samples"] == 1
    assert result["by_forecast_mode"]["ml"]["samples"] == 1
    assert result["delivered_mode_counts"] == {"kinematic_fallback": 1}
    assert result["delivered_mode_counts"].get("ml", 0) != result["by_forecast_mode"]["ml"]["samples"]


def test_evaluate_for_horizon_counts_delivered_mode_without_target_frame(monkeypatch, tmp_path):
    import json
    import sys
    import types
    from datetime import datetime

    sys.modules.pop("accuracy_tracker", None)
    monkeypatch.setitem(sys.modules, "debug_utils", types.SimpleNamespace(debug_log=lambda *args, **kwargs: None))
    import accuracy_tracker

    ev = tmp_path / "evaluation"
    ev.mkdir()
    monkeypatch.setattr(accuracy_tracker, "EVAL_DIR", str(ev), raising=False)
    monkeypatch.setattr(accuracy_tracker, "DETAILS_FILE", str(ev / "forecast_error_details.jsonl"), raising=False)
    monkeypatch.setattr(accuracy_tracker, "HISTORY_FILE", str(ev / "accuracy_history.jsonl"), raising=False)

    obj_dir = tmp_path / "objects"
    obj_dir.mkdir()
    t0 = datetime(2026, 6, 18, 12, 0, 0)
    (obj_dir / f"{t0:%Y-%m-%d_%H-%M-%S}.json").write_text(json.dumps([{
        "id": "WX-B288-1", "cell_id": "WX-B288-1",
        "x": 10.0, "y": 20.0, "lat": 46.70, "lon": 14.10,
        "forecast_x_30": 10.0, "forecast_y_30": 20.0,
        "forecast_lat_30": 46.71, "forecast_lon_30": 14.11,
        "forecast_mode_30": "ml", "kinematic_source_30": "ml_model",
    }]), encoding="utf-8")
    monkeypatch.setitem(accuracy_tracker.SAVE_PATHS, "objects", str(obj_dir))

    result = accuracy_tracker.evaluate_for_horizon(30, since_hours=24)

    assert result["samples"] == 1
    assert result["no_target_frame"] == 1
    assert result["by_forecast_mode"]["ml"]["no_target_frame"] == 1
    assert result["delivered_mode_counts"] == {"ml": 1}
