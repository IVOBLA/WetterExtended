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
        '{"timestamp_utc":"2026-07-02T00:00:00Z","breakdown_by_forecast_mode":{"10":{"kinematic_fallback":{"mae_km":0.7,"samples":90,"verified":90},"ml":{"mae_km":0.6,"samples":10,"verified":8,"no_target_frame":2}}}}\n',
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
    monkeypatch.setattr(wetter_app.runtime_config, "get", lambda key, default=None: [10] if key == "ML_FORECAST_HORIZONS_MIN" else default)

    monkeypatch.setattr(
        "prediction._ml_runtime_gate_by_horizon",
        lambda horizons: {int(h): {"reason": "shadow_mode"} for h in horizons},
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
    assert ml_payload["ml_gate_reasons"] == {"10": "shadow_mode"}
    assert ml_payload["verification_coverage_by_horizon"]["10"] == round(98 / 102, 4)

    assert diag_resp.status_code == 200
    assert "bias_by_horizon" in diag_resp.get_json()
