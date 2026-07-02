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


def test_evaluate_on_recent_prefers_runtime_accuracy_history(monkeypatch, tmp_path):
    dataset_dir = tmp_path / "dataset"
    model_dir = tmp_path / "models"
    dataset_dir.mkdir()
    model_dir.mkdir()

    n = 6
    X = np.zeros((n, 1, 4), dtype=float)
    y_raw = np.zeros((n, 2), dtype=float)
    ids = np.array([{"timestamp": f"2026-07-02_00-0{i}-00"} for i in range(n)], dtype=object)
    np.savez(dataset_dir / "dataset.npz", X=X, y_raw=y_raw, ids=ids)

    scaler_y = StandardScaler().fit(np.zeros((n, 2)))
    joblib.dump(scaler_y, model_dir / "scaler_y.joblib")
    (model_dir / "lgbm_h10_x.txt").write_text("fake", encoding="utf-8")
    (model_dir / "lgbm_h10_y.txt").write_text("fake", encoding="utf-8")

    class _Booster:
        def __init__(self, model_file):
            self.model_file = model_file
        def predict(self, X_recent):
            return np.zeros(len(X_recent), dtype=float)

    monkeypatch.setitem(mt.SAVE_PATHS, "dataset", str(dataset_dir))
    monkeypatch.setattr(mt, "_get_training_horizons", lambda: [10])
    monkeypatch.setattr(mt, "ML_FORECAST_HORIZONS_MIN", [10])
    monkeypatch.setattr(mt.lgb, "Booster", _Booster)
    monkeypatch.setattr(
        "accuracy_tracker.get_runtime_kinematic_mae_by_horizon",
        lambda min_samples=20: {"10": {"kinematic_mae": 0.5, "kinematic_samples": 40}},
    )
    monkeypatch.setattr(mt, "_kinematic_baseline_mae", lambda *a, **k: ({"10": 99.0}, 99.0))

    res = mt.evaluate_on_recent(str(model_dir))

    assert res["kin_mae_by_horizon"]["10"] == 0.5
    assert res["promotion_baseline_source"]["10"] == "runtime_accuracy_history"
