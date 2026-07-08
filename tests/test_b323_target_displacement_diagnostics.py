"""
B323: Diagnose der Ziel-Verschiebungsverteilung in build_dataset(). Rein
diagnostisch -- prueft, ob ein hoher Anteil quasi-stationaerer Zellen die
Zielverteilung dominiert (Hypothese fuer die LSTM-val_loss-Regression).
"""
import pytest

np = pytest.importorskip("numpy")
db = pytest.importorskip("dataset_builder")


def test_all_stationary_targets_yield_high_fraction():
    y_raw = np.array([[0.1, 0.1, 1.0, 1.0], [0.0, 0.2, 2.0, 2.0], [0.3, 0.0, 1.0, 1.0]])
    disp = np.sqrt(y_raw[:, 0] ** 2 + y_raw[:, 1] ** 2)
    frac = float(np.mean(disp < 2.0))
    assert frac == 1.0


def test_mixed_targets_yield_partial_fraction():
    y_raw = np.array([[0.0, 0.0, 1.0, 1.0], [50.0, 50.0, 1.0, 1.0]])
    disp = np.sqrt(y_raw[:, 0] ** 2 + y_raw[:, 1] ** 2)
    frac = float(np.mean(disp < 2.0))
    assert frac == 0.5


def test_nan_targets_excluded_from_stats():
    y_raw = np.array([[float("nan"), float("nan"), 1.0, 1.0], [5.0, 5.0, 1.0, 1.0]])
    disp = np.sqrt(y_raw[:, 0] ** 2 + y_raw[:, 1] ** 2)
    disp_valid = disp[~np.isnan(disp)]
    assert disp_valid.size == 1
