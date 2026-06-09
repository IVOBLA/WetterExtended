"""B108: Sicherstellung dass path_*-Features VOR _build_sequence() gesetzt werden.
Kinematic-First garantiert Train/Inference-Konsistenz."""
import inspect

import pytest


def test_b108_path_features_present_in_ml_cell_features():
    """B108: path_*-Features müssen in ML_CELL_FEATURES sein."""
    config = pytest.importorskip("config")
    path_feats = [f for f in config.ML_CELL_FEATURES if str(f).startswith("path_")]
    assert len(path_feats) > 0, (
        "B108: path_*-Features fehlen in ML_CELL_FEATURES. "
        "Nach dem Kinematic-First-Fix müssen sie wieder enthalten sein."
    )


def test_b108_ml_num_features_consistent():
    """ML_NUM_FEATURES muss mit len(ML_CELL_FEATURES) + Stations + Zeit übereinstimmen."""
    config = pytest.importorskip("config")
    expected = (
        len(config.ML_CELL_FEATURES)
        + len(config.ML_STATION_FEATURES)
        + len(config.ML_TIME_FEATURES)
    )
    assert config.ML_NUM_FEATURES == expected, (
        f"ML_NUM_FEATURES={config.ML_NUM_FEATURES} != Feature-Summe {expected}"
    )


def test_b108_compute_path_weather_signature():
    """_compute_path_weather muss 4 Parameter akzeptieren."""
    pred = pytest.importorskip("prediction")
    assert hasattr(pred, "_compute_path_weather"), "_compute_path_weather nicht gefunden"
    sig = inspect.signature(pred._compute_path_weather)
    params = list(sig.parameters)
    assert len(params) == 4, (
        f"_compute_path_weather erwartet 4 Parameter (obj, horizons, snapshot, max_dist), "
        f"hat aber: {params}"
    )


def test_b108_append_kinematic_sets_forecast_lat_lon():
    """_append_kinematic muss forecast_lat_H/forecast_lon_H auf obj setzen."""
    pred = pytest.importorskip("prediction")
    obj = {
        "id": "TEST", "lat": 46.62, "lon": 14.31,
        "x": 100.0, "y": 200.0, "vx": 2.0, "vy": -1.0,
        "size": 5.0, "area": 3.0,
    }
    import config
    horizons = config.ML_FORECAST_HORIZONS_MIN
    temp_fc = {h: [] for h in horizons}
    pred._append_kinematic(obj, temp_fc)
    for h in horizons:
        assert f"forecast_lat_{h}" in obj, f"forecast_lat_{h} nicht auf obj gesetzt"
        assert f"forecast_lon_{h}" in obj, f"forecast_lon_{h} nicht auf obj gesetzt"


def test_b108_path_weather_uses_forecast_positions():
    """_compute_path_weather liest forecast_lat_H/forecast_lon_H vom obj."""
    pred = pytest.importorskip("prediction")
    import config
    horizons = config.ML_FORECAST_HORIZONS_MIN
    obj = {"id": "TEST", "lat": 46.62, "lon": 14.31}
    for h in horizons:
        obj[f"forecast_lat_{h}"] = 46.62 + h * 0.001
        obj[f"forecast_lon_{h}"] = 14.31 + h * 0.001
    snapshot = {"locations": [
        {"lat": 46.62, "lon": 14.31, "cape": 1200.0, "li": -3.0,
         "cin": -50.0, "lapse_700_500": 7.0, "wind_700hpa": 40.0}
    ]}
    pred._compute_path_weather(obj, horizons, snapshot, 100.0)
    assert obj.get("path_cape_end", 0.0) > 0, "path_cape_end soll > 0 sein"
    assert "path_li_end" in obj


def test_b108_predict_positions_sets_path_before_build_sequence():
    """B108: Kinematic-First-Block muss vor _build_sequence() im ML-Pfad liegen."""
    pred = pytest.importorskip("prediction")
    source = inspect.getsource(pred.predict_positions)
    prefill_idx = source.find("_append_kinematic(obj, _temp_fc)")
    build_idx = source.find("seq = _build_sequence")
    assert prefill_idx != -1, "B108-Kinematic-First-Vorbelegung nicht gefunden"
    assert build_idx != -1, "_build_sequence-Aufruf nicht gefunden"
    assert prefill_idx < build_idx, "path_*-Vorbelegung muss vor _build_sequence() erfolgen"
    assert "for _o in objects" not in source, (
        "Alter B95-Pfad-Wetter-Block darf nach dem Objekt-Loop nicht erneut laufen"
    )
