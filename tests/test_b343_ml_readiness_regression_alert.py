"""B343: check_ml_readiness() erkennt den Uebergang
ml_artifacts_available true->false als Regression, nicht als Cold-Start."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ml_readiness


def _write_prev_readiness(evaluation_dir, ml_artifacts_available):
    os.makedirs(evaluation_dir, exist_ok=True)
    with open(os.path.join(evaluation_dir, "ml_readiness.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "checked_at_utc": "2026-07-05T10:00:00Z",
                "ml_artifacts_available": ml_artifacts_available,
            },
            f,
        )


def test_regression_alert_true_when_artifacts_were_available_before(tmp_path, monkeypatch):
    evaluation_dir = tmp_path / "evaluation"
    _write_prev_readiness(evaluation_dir, ml_artifacts_available=True)

    monkeypatch.setattr(
        ml_readiness,
        "SAVE_PATHS",
        {
            **ml_readiness.SAVE_PATHS,
            "evaluation": str(evaluation_dir),
            "models": str(tmp_path / "models"),
            "dataset": str(tmp_path / "dataset"),
        },
    )
    empty_model_dir = tmp_path / "models" / "current"

    result = ml_readiness.check_ml_readiness(write_json=True, model_dir=str(empty_model_dir))

    assert result["ml_artifacts_available"] is False
    assert result["regression_alert"] is True
    assert "true" in result["regression_reason"] and "false" in result["regression_reason"]


def test_no_regression_alert_on_true_cold_start(tmp_path, monkeypatch):
    evaluation_dir = tmp_path / "evaluation"
    # Kein vorheriges ml_readiness.json vorhanden -> echter Cold-Start.

    monkeypatch.setattr(
        ml_readiness,
        "SAVE_PATHS",
        {
            **ml_readiness.SAVE_PATHS,
            "evaluation": str(evaluation_dir),
            "models": str(tmp_path / "models"),
            "dataset": str(tmp_path / "dataset"),
        },
    )
    empty_model_dir = tmp_path / "models" / "current"

    result = ml_readiness.check_ml_readiness(write_json=True, model_dir=str(empty_model_dir))

    assert result["ml_artifacts_available"] is False
    assert result["regression_alert"] is False
    assert result["regression_reason"] is None
