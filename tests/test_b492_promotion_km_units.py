"""B492/F-ML-001: Modell-Promotion verglich ML-MAE im Radar-Pixel-Raum direkt mit
kinematischer Betriebs-MAE in km. Diese Tests verankern, dass evaluate_on_recent()
jetzt eine echte, ueber denselben Transform-Pfad wie die Laufzeit-Inferenz berechnete
km-Metrik liefert, und dass Promotion diese (nicht mehr die Pixel-Metrik) nutzt."""
import inspect
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import model_training as mt  # noqa: E402


def _fake_target_to_latlon(origin_x, origin_y, dx, dy, target_encoding):
    if target_encoding == "delta":
        bx, by = origin_x + dx, origin_y + dy
    else:
        bx, by = dx, dy
    base_lat = 46.6
    km_per_unit = 0.01
    lat = base_lat + (by * km_per_unit) / 111.0
    lon = 14.0 + (bx * km_per_unit) / (111.0 * math.cos(math.radians(base_lat)))
    return lat, lon


def test_promotion_reads_mae_km_total_not_mae_total():
    """Kontrolltest: die Promotion-Funktion darf 'mae_total' (Pixel-/Zielraum)
    nicht mehr als Vergleichswert fuer _mae_new/_mae_old verwenden."""
    src = inspect.getsource(mt)
    assert '_mae_new     = float(new_eval.get("mae_km_total"' in src
    assert '_mae_old     = float(old_eval.get("mae_km_total"' in src
    assert '_mae_new     = float(new_eval.get("mae_total"' not in src
    assert '_mae_old     = float(old_eval.get("mae_total"' not in src


def test_target_to_latlon_uses_shared_transform(monkeypatch):
    """_target_to_latlon() muss ueber prediction._decode_ml_position und
    geo_utils.pixel_to_geo gehen — denselben Pfad wie die Laufzeit-Inferenz —
    statt eine eigene, potenziell abweichende Umrechnung zu implementieren."""
    calls = {"decode": 0, "geo": 0}

    def _fake_decode(obj, x_raw, y_raw, target_encoding):
        calls["decode"] += 1
        return float(x_raw), float(y_raw)

    def _fake_pixel_to_geo(x, y):
        calls["geo"] += 1
        return 46.6, 14.0

    monkeypatch.setattr("prediction._decode_ml_position", _fake_decode)
    monkeypatch.setattr("geo_utils.pixel_to_geo", _fake_pixel_to_geo)
    lat, lon = mt._target_to_latlon(100.0, 200.0, 5.0, -3.0, "delta")
    assert calls == {"decode": 1, "geo": 1}
    assert (lat, lon) == (46.6, 14.0)


def test_km_and_px_error_ranking_can_diverge(monkeypatch, tmp_path):
    """Regressionsbeweis fuer F-ML-001: ein Kandidat mit kleinerem Pixelfehler kann
    real (in km) schlechter sein als ein Kandidat mit groesserem Pixelfehler, sobald
    die Geometrie nicht linear-uniform ist. evaluate_on_recent() muss beide Groessen
    getrennt fuehren, damit die Promotion nicht versehentlich die falsche waehlt."""
    import numpy as np
    import joblib
    from sklearn.preprocessing import StandardScaler

    monkeypatch.setattr(mt, "_target_to_latlon", _fake_target_to_latlon)

    dataset_dir = tmp_path / "dataset"; model_dir = tmp_path / "models"
    dataset_dir.mkdir(); model_dir.mkdir()
    n = 5
    X = np.zeros((n, 1, 4), dtype=float)
    y_raw = np.zeros((n, 2), dtype=float)
    ids = np.array([{"timestamp": f"2026-07-02_00-0{i}-00"} for i in range(n)], dtype=object)
    np.savez(dataset_dir / "dataset.npz", X=X, y_raw=y_raw, ids=ids)

    scaler_y = StandardScaler().fit(np.zeros((n, 2)))
    joblib.dump(scaler_y, model_dir / "scaler_y.joblib")
    scaler_X = StandardScaler().fit(np.zeros((n, 4)))
    joblib.dump(scaler_X, model_dir / "scaler_X.joblib")
    (model_dir / "lgbm_h10_x.txt").write_text("fake", encoding="utf-8")
    (model_dir / "lgbm_h10_y.txt").write_text("fake", encoding="utf-8")

    class _Booster:
        def __init__(self, model_file):
            self.model_file = model_file
        def predict(self, X_recent):
            return np.full(len(X_recent), 2.0, dtype=float)  # konstanter Pixel-Fehler

    monkeypatch.setitem(mt.SAVE_PATHS, "dataset", str(dataset_dir))
    monkeypatch.setattr(mt, "_get_training_horizons", lambda: [10])
    monkeypatch.setattr(mt, "ML_FORECAST_HORIZONS_MIN", [10])
    monkeypatch.setattr(mt.lgb, "Booster", _Booster)
    monkeypatch.setattr("accuracy_tracker.get_runtime_kinematic_mae_by_horizon", lambda min_samples=20: {})

    res = mt.evaluate_on_recent(str(model_dir))
    assert "mae_km_total" in res and "mae_px_total" in res
    assert res["mae_px_total"] == res["mae_total"], "mae_total bleibt Alias fuer mae_px_total"
    assert res["mae_km_total"] != float("inf"), "km-Metrik muss bei vorhandenem scaler_X berechnet werden"
    assert res["paired_samples_by_horizon"].get("10") == n
