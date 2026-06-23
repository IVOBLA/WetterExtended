"""B242: _compute_holdout_metrics misst den echten Fehler (roh vs roh), nicht roh vs skaliert."""
import pytest

np = pytest.importorskip("numpy")
mt = pytest.importorskip("model_training")
StandardScaler = pytest.importorskip("sklearn.preprocessing").StandardScaler


class _FakeLSTM:
    """Liefert skalierte Vorhersagen, die (roh) genau 3 px neben den Zielen liegen."""
    def __init__(self, scaler, y_raw_target):
        self._sc = scaler
        self._t = y_raw_target

    def predict(self, X, verbose=0):
        return self._sc.transform(self._t + 3.0)


def test_holdout_mae_reflects_real_error_not_position_magnitude(monkeypatch, tmp_path):
    if mt.np is None:
        pytest.skip("numpy fehlt")
    rng = np.random.default_rng(0)
    y_raw = rng.uniform(50.0, 400.0, size=(40, 10))      # rohe px-Targets
    sc = StandardScaler().fit(y_raw)
    y_scaled = sc.transform(y_raw)                        # = dataset["y"][mask] (skaliert)
    X_h = np.zeros((40, mt.ML_SEQUENCE_LENGTH, 4), dtype=float)  # vom Fake ignoriert

    monkeypatch.setattr(mt, "load_model", lambda p, compile=False: _FakeLSTM(sc, y_raw))
    monkeypatch.setattr(mt.joblib, "load", lambda p: sc)
    monkeypatch.setattr(mt.os.path, "exists", lambda p: True)

    res = mt._compute_holdout_metrics(X_h, y_scaled, str(tmp_path))
    assert res["mae_px"] is not None
    # Echter Fehler ist ~3 px. Mit dem Bug (roh vs skaliert) wäre er ~Positionsbetrag (>>50).
    assert res["mae_px"] < 20.0, f"mae_px={res['mae_px']} deutet auf roh-vs-skaliert-Bug"


def test_holdout_handles_nan_masked_horizons(monkeypatch, tmp_path):
    if mt.np is None:
        pytest.skip("numpy fehlt")
    rng = np.random.default_rng(1)
    y_raw = rng.uniform(50.0, 400.0, size=(30, 10))
    sc = StandardScaler().fit(y_raw)
    y_scaled = sc.transform(y_raw)
    y_scaled[5, 8:10] = np.nan                          # maskierter Horizont +60
    X_h = np.zeros((30, mt.ML_SEQUENCE_LENGTH, 4), dtype=float)

    monkeypatch.setattr(mt, "load_model", lambda p, compile=False: _FakeLSTM(sc, y_raw))
    monkeypatch.setattr(mt.joblib, "load", lambda p: sc)
    monkeypatch.setattr(mt.os.path, "exists", lambda p: True)

    res = mt._compute_holdout_metrics(X_h, y_scaled, str(tmp_path))
    assert res["mae_px"] is not None
    assert not np.isnan(res["mae_px"])                  # nanmean ignoriert die Maske
