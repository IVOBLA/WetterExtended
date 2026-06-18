"""
P-T08 — Tests für Per-Horizont-Maskierung, partielle Abdeckung & Radaralter.

Abgedeckt (dependency-arm):
  - validate_sample akzeptiert teilweise maskierte Ziele (NaN)
  - validate_sample lehnt vollständig maskierte Ziele ab
  - validate_sample überspringt Jump-Check bei maskiertem +30
  - _predict_lgbm_vector liefert NaN für fehlende Horizont-Modelle
  - _masked_mse ignoriert NaN-Ziele (nur wenn TensorFlow vorhanden)
"""
import math
import pytest


# ---------------------------------------------------------------------------
# validate_sample
# ---------------------------------------------------------------------------

def _seq_ok():
    """Minimale gültige Sequenz (eine Frame-Liste mit endlichen Werten)."""
    return [[0.0, 1.0, 2.0]]


def test_validate_accepts_partial_masked_targets():
    from data_quality import validate_sample
    # 5 Horizonte × (x,y) = 10 Ziele; +40/+60 maskiert (NaN)
    target = [10.0, 20.0, 11.0, 21.0, 12.0, 22.0, float("nan"), float("nan"), float("nan"), float("nan")]
    ok, reason = validate_sample(_seq_ok(), target, seq_context=[{"x": 10.0, "y": 20.0}])
    assert ok is True, f"Teilmaskiertes Sample sollte gültig sein (reason={reason})"


def test_validate_rejects_fully_masked_targets():
    from data_quality import validate_sample
    target = [float("nan")] * 10
    ok, reason = validate_sample(_seq_ok(), target, seq_context=[{"x": 0.0, "y": 0.0}])
    assert ok is False
    assert reason == "no valid target horizon"


def test_validate_skips_jump_check_when_h30_masked():
    from data_quality import validate_sample
    # +30 (Index 4/5) maskiert → Jump-Check übersprungen, trotz großem +10-Sprung
    target = [9999.0, 9999.0, 11.0, 21.0, float("nan"), float("nan"), 13.0, 23.0, 14.0, 24.0]
    ok, _ = validate_sample(_seq_ok(), target, seq_context=[{"x": 0.0, "y": 0.0}])
    assert ok is True


def test_validate_rejects_nonfinite_in_sequence():
    from data_quality import validate_sample
    bad_seq = [[0.0, float("inf"), 2.0]]
    target = [10.0, 20.0]
    ok, reason = validate_sample(bad_seq, target, seq_context=[{"x": 0.0, "y": 0.0}])
    assert ok is False
    assert reason == "non-finite values"


# ---------------------------------------------------------------------------
# _predict_lgbm_vector
# ---------------------------------------------------------------------------

def test_predict_lgbm_vector_nan_for_missing(monkeypatch):
    pytest.importorskip("numpy")
    import numpy as np
    import prediction

    # Nur +10 hat Modelle; restliche Horizonte fehlen
    monkeypatch.setattr(prediction, "_get_horizons", lambda: [10, 20, 30, 40, 60])

    class _FakeBooster:
        def predict(self, frame):
            return [42.0]

    models = {"lgbm_h10_x": _FakeBooster(), "lgbm_h10_y": _FakeBooster()}
    vec = prediction._predict_lgbm_vector(models, [[0.0]])

    assert vec.shape[0] == 10
    assert vec[0] == 42.0 and vec[1] == 42.0          # +10 vorhanden
    assert np.all(np.isnan(vec[2:]))                  # +20..+60 fehlen → NaN


# ---------------------------------------------------------------------------
# _masked_mse (nur mit TensorFlow)
# ---------------------------------------------------------------------------

def test_masked_mse_ignores_nan():
    pytest.importorskip("tensorflow")
    import tensorflow as tf
    from model_training import _masked_mse

    # y_true: erstes Element gültig (Fehler 0), zweites maskiert (NaN)
    y_true = tf.constant([[5.0, float("nan")]])
    y_pred = tf.constant([[5.0, 999.0]])   # großer Fehler im maskierten Element
    loss = float(_masked_mse(y_true, y_pred).numpy())
    assert loss == pytest.approx(0.0, abs=1e-6), (
        f"Maskiertes Element (NaN) darf nicht in den Loss eingehen, loss={loss}"
    )


def test_masked_mse_counts_valid():
    pytest.importorskip("tensorflow")
    import tensorflow as tf
    from model_training import _masked_mse

    y_true = tf.constant([[0.0, float("nan")]])
    y_pred = tf.constant([[2.0, 999.0]])   # Fehler 2 im gültigen Element → MSE = 4
    loss = float(_masked_mse(y_true, y_pred).numpy())
    assert loss == pytest.approx(4.0, abs=1e-4)


def test_predict_positions_marks_partial_lgbm_horizons_per_horizon(monkeypatch):
    pytest.importorskip("numpy")
    import numpy as np
    import prediction

    monkeypatch.setattr(prediction, "_get_horizons", lambda: [10, 20, 30])
    monkeypatch.setattr(prediction, "ML_SEQUENCE_LENGTH", 1)
    monkeypatch.setattr(prediction, "ML_NUM_FEATURES", 1)
    monkeypatch.setattr(prediction, "_UF", 1.0)
    monkeypatch.setattr(prediction, "pixel_to_geo", lambda x, y: (float(y) / 100.0, float(x) / 100.0))
    monkeypatch.setattr(prediction, "_build_sequence", lambda *args, **kwargs: np.asarray([[0.0]], dtype=float))
    monkeypatch.setattr(prediction, "load_lstm", lambda: None)
    monkeypatch.setattr(prediction, "load_intensification_model", lambda: None)
    monkeypatch.setattr(prediction, "_load_intensity_regressors", lambda: (None, None))
    monkeypatch.setattr(prediction, "_load_atmosphere_snapshot", lambda: {})

    class _ScalerX:
        def transform(self, seq):
            return np.asarray(seq, dtype=float)

    class _ScalerY:
        def inverse_transform(self, arr):
            return np.asarray(arr, dtype=float)

    class _FakeBooster:
        def __init__(self, value):
            self.value = value

        def predict(self, frame):
            return [self.value]

    monkeypatch.setattr(prediction, "load_scalers", lambda: (_ScalerX(), _ScalerY()))
    monkeypatch.setattr(
        prediction,
        "load_lgbm_models",
        lambda: {"lgbm_h10_x": _FakeBooster(110.0), "lgbm_h10_y": _FakeBooster(210.0)},
    )

    obj = {
        "id": "partial",
        "x": 100.0,
        "y": 200.0,
        "lat": 47.0,
        "lon": 15.0,
        "vx": 1.0,
        "vy": 1.0,
        "of_available": 0,
    }

    fc10, fc20, fc30 = prediction.predict_positions([obj], "2026-06-18_12-00-00", [])

    assert obj["forecast_mode"] == "ml"
    assert obj["forecast_mode_10"] == "ml"
    assert obj["forecast_mode_20"] == "kinematic"
    assert obj["forecast_mode_30"] == "kinematic"
    assert obj["kinematic_source_10"] is None
    assert obj["kinematic_source_20"] == obj["kinematic_source"]
    assert fc10[0]["forecast_mode_horizon"] == "ml"
    assert fc20[0]["forecast_mode_horizon"] == "kinematic"
    assert fc30[0]["forecast_mode_horizon"] == "kinematic"
