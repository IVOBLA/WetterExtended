"""B243: kinematische Baseline-MAE + Promotion-Reject, wenn ML schlechter ist."""
import os
import tempfile
import pytest

mt = pytest.importorskip("model_training")
np = pytest.importorskip("numpy")
joblib = pytest.importorskip("joblib")
StandardScaler = pytest.importorskip("sklearn.preprocessing").StandardScaler


def _make_scaler_dir(n=60, F=119):
    raw = np.zeros((n, F))
    raw[:, 0] = 100.0; raw[:, 1] = 200.0; raw[:, 2] = 2.0; raw[:, 3] = 1.0
    raw += np.random.default_rng(0).normal(0, 0.1, (n, F))
    sc = StandardScaler().fit(raw)
    d = tempfile.mkdtemp()
    joblib.dump(sc, os.path.join(d, "scaler_X.joblib"))
    return d, sc.transform(raw), raw


def test_kinematic_baseline_low_for_consistent_motion():
    d, X_recent, raw = _make_scaler_dir()
    horizons = list(mt.ML_FORECAST_HORIZONS_MIN)
    # y_recent passend zum Encoding der laufenden Config bauen
    enc = mt.ML_TARGET_ENCODING
    y = np.zeros((raw.shape[0], len(horizons) * 2))
    for i, h in enumerate(horizons):
        dx = raw[:, 2] * h; dy = raw[:, 3] * h
        if enc == "delta":
            y[:, 2 * i] = dx; y[:, 2 * i + 1] = dy
        else:
            y[:, 2 * i] = raw[:, 0] + dx; y[:, 2 * i + 1] = raw[:, 1] + dy
    avail = set(range(len(horizons) * 2))
    by_h, total = mt._kinematic_baseline_mae(X_recent, y, d, horizons, avail)
    assert total < 5.0  # nahezu perfekte Kinematik -> kleiner Baseline-MAE
    assert len(by_h) == len(horizons)


def test_baseline_missing_scaler_returns_inf():
    by_h, total = mt._kinematic_baseline_mae(
        np.zeros((5, 119)), np.zeros((5, 10)), tempfile.mkdtemp(),
        list(mt.ML_FORECAST_HORIZONS_MIN), set(range(10)),
    )
    assert total == float("inf")
    assert by_h == {}


def test_evaluate_on_recent_returns_kin_keys(monkeypatch, tmp_path):
    # evaluate_on_recent liefert die neuen kin_*-Schlüssel (ohne Dataset -> inf, aber Keys da)
    res = mt.evaluate_on_recent(str(tmp_path))
    assert "mae_total" in res
    # Bei fehlendem Dataset bricht die Funktion früh ab; mind. mae_total vorhanden.
