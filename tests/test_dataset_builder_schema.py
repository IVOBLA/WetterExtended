import json

import pytest

import feature_schema


def test_build_dataset_rejects_legacy_and_accepts_schema_samples(tmp_path, monkeypatch):
    db = pytest.importorskip("dataset_builder")
    if db.np is None or db.joblib is None or db.StandardScaler is None:
        pytest.skip("optionale ML-Abhängigkeiten fehlen")

    objects = tmp_path / "objects"
    weather = tmp_path / "weather"
    dataset = tmp_path / "dataset"
    models = tmp_path / "models"
    for path in (objects, weather, dataset, models):
        path.mkdir()

    monkeypatch.setitem(db.SAVE_PATHS, "objects", str(objects))
    monkeypatch.setitem(db.SAVE_PATHS, "weather", str(weather))
    monkeypatch.setitem(db.SAVE_PATHS, "dataset", str(dataset))
    monkeypatch.setitem(db.SAVE_PATHS, "models", str(models))
    monkeypatch.setattr(db, "ML_SEQUENCE_LENGTH", 1)
    monkeypatch.setattr(db, "ML_CELL_FEATURES", [])
    monkeypatch.setattr(db, "ML_STATION_FEATURES", [])
    monkeypatch.setattr(db, "_get_ds_horizons", lambda: [10])
    monkeypatch.setattr(db, "_schema_policy_allows_legacy", lambda: False)

    class _Frame:
        def __init__(self, rows):
            self.rows = rows

        def to_parquet(self, path, index=False):
            (tmp_path / "tabular_called.txt").write_text(str(len(self.rows)), encoding="utf-8")

    monkeypatch.setattr(db.pd, "DataFrame", lambda rows: _Frame(rows))

    def write_pair(ts, obj_payload, weather_payload):
        (objects / f"{ts}.json").write_text(json.dumps(obj_payload), encoding="utf-8")
        (weather / f"{ts}.json").write_text(json.dumps(weather_payload), encoding="utf-8")

    write_pair("2026-01-01_00-00-00", [{"id": "cell", "x": 0, "y": 0, "lat": 46.7, "lon": 14.3}], [])
    write_pair(
        "2026-01-01_00-10-00",
        feature_schema.attach_schema_metadata([{"id": "cell", "x": 1, "y": 2, "lat": 46.7, "lon": 14.3}]),
        feature_schema.attach_schema_metadata([]),
    )
    write_pair(
        "2026-01-01_00-20-00",
        feature_schema.attach_schema_metadata([{"id": "cell", "x": 4, "y": 6, "lat": 46.7, "lon": 14.3}]),
        feature_schema.attach_schema_metadata([]),
    )

    result = db.build_dataset(model_save_dir=str(models / "v_test"))

    assert result["schema_compatible_samples"] >= 1
    assert result["schema_legacy_samples"] == 1
    assert result["rejection_reasons"]["legacy_missing_schema"] == 1
    assert len(result["X"]) == 1
    assert result["feature_schema_hash"] == feature_schema.get_current_feature_schema()["feature_schema_hash"]
