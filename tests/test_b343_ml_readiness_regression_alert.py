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


def test_regression_alert_stays_latched_across_polls(tmp_path, monkeypatch):
    """Codex-Review: der Alarm darf nicht nach einem einzigen Folge-Poll
    verschwinden, solange die Artefakte weiterhin fehlen."""
    import ml_readiness

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

    first = ml_readiness.check_ml_readiness(write_json=True, model_dir=str(empty_model_dir))
    assert first["regression_alert"] is True

    # Zweiter Poll: Artefakte fehlen weiterhin -> Alarm MUSS latched bleiben.
    second = ml_readiness.check_ml_readiness(write_json=True, model_dir=str(empty_model_dir))
    assert second["regression_alert"] is True
    assert second["regression_reason"]

    # Dritter Poll: ebenfalls weiterhin latched.
    third = ml_readiness.check_ml_readiness(write_json=True, model_dir=str(empty_model_dir))
    assert third["regression_alert"] is True


def test_regression_alert_clears_on_recovery(tmp_path, monkeypatch):
    """Sobald ml_artifacts_available wieder true wird, muss der Alarm
    zurueckgesetzt werden."""
    import ml_readiness

    evaluation_dir = tmp_path / "evaluation"
    _write_prev_readiness(evaluation_dir, ml_artifacts_available=False)
    # Simuliere bereits aktiven, latched Alarm aus einem Vorlauf.
    with open(evaluation_dir / "ml_readiness.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "checked_at_utc": "2026-07-11T10:00:00Z",
                "ml_artifacts_available": False,
                "regression_alert": True,
                "regression_reason": "war schon kaputt",
            },
            f,
        )

    model_dir = tmp_path / "models" / "current"
    model_dir.mkdir(parents=True)
    for name in ("scaler_X.joblib", "scaler_y.joblib", "lgbm_h60_x.txt", "lgbm_h60_y.txt"):
        (model_dir / name).write_text("placeholder", encoding="utf-8")

    class _FakeScalerX:
        n_features_in_ = ml_readiness.ML_NUM_FEATURES

    class _FakeScalerY:
        n_features_in_ = 2

    class _FakeJoblib:
        @staticmethod
        def load(path):
            return _FakeScalerY() if str(path).endswith("scaler_y.joblib") else _FakeScalerX()

    class _FakeBooster:
        def __init__(self, model_file):
            self.model_file = model_file

        def num_feature(self):
            return ml_readiness.ML_NUM_FEATURES

    class _FakeLightGBM:
        Booster = _FakeBooster

    def _fake_opt(name):
        if name == "joblib":
            return _FakeJoblib
        if name == "lightgbm":
            return _FakeLightGBM
        return None

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
    monkeypatch.setattr(ml_readiness, "_opt", _fake_opt)
    monkeypatch.setattr(ml_readiness, "_runtime_horizons", lambda: [60])

    result = ml_readiness.check_ml_readiness(write_json=True, model_dir=str(model_dir))
    assert result["ml_artifacts_available"] is True
    assert result["regression_alert"] is False
    assert result["regression_reason"] is None
