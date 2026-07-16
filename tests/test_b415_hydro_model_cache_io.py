import json
import pickle

import hydro_flood_ml as h


def _install_model(monkeypatch, tmp_path):
    monkeypatch.setattr(h, "HYDRO_MODEL_CURRENT_DIR", tmp_path)
    monkeypatch.setattr(h, "HYDRO_MODEL_FILENAME", "model.joblib")
    h._MODEL_CACHE.clear()
    meta = {"promoted": True, "feature_schema_version": h.FEATURE_SCHEMA_VERSION,
            "feature_schema_hash": h._feature_schema_hash(), "feature_names": h.HYDRO_FLOOD_ML_FEATURES,
            "new_active_version": "cache-test"}
    artifact = {"feature_schema_version": h.FEATURE_SCHEMA_VERSION,
                "feature_schema_hash": h._feature_schema_hash(), "feature_names": h.HYDRO_FLOOD_ML_FEATURES,
                "type": "feature_linear_residual", "model": {"feature_idx": 0, "slope": 0.0, "intercept": 0.25}}
    (tmp_path / "model.joblib").write_bytes(pickle.dumps(artifact))
    (tmp_path / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    h._write_model_manifest(tmp_path, meta)


def test_eighty_stations_hash_and_deserialize_once_then_hit(monkeypatch, tmp_path):
    _install_model(monkeypatch, tmp_path)
    hashes = 0
    loads = 0
    real_hash = h._file_sha256
    real_load = h._load_artifact

    def counted_hash(path):
        nonlocal hashes
        hashes += 1
        return real_hash(path)

    def counted_load(path):
        nonlocal loads
        loads += 1
        return real_load(path)

    monkeypatch.setattr(h, "_file_sha256", counted_hash)
    monkeypatch.setattr(h, "_load_artifact", counted_load)
    monkeypatch.setattr(h, "build_feature_row", lambda station, **kwargs: {
        **{name: 1.0 for name in h.HYDRO_FLOOD_ML_FEATURES},
        "station_id": station["station_id"], "current_q_m3s": 2.0,
        "physical_predicted_q_delta_m3s": 0.5, "station_q_threshold_m3s": 10.0,
    })
    monkeypatch.setattr(h, "load_q_trend_history", lambda: {})
    stations = [{"station_id": str(i)} for i in range(80)]

    first = h.evaluate_live_flood_risk(stations=stations, live={}, cells=[], write=False)
    assert len(first["stations"]) == 80
    assert hashes <= 3
    assert loads == 1
    assert [row["model_cache_status"] for row in first["stations"]].count("miss") == 1
    hashes = 0
    second = h.evaluate_live_flood_risk(stations=stations, live={}, cells=[], write=False)
    assert len(second["stations"]) == 80
    assert hashes == 0
    assert loads == 1


def test_stat_key_changes_on_touch_and_directory_swap(monkeypatch, tmp_path):
    current = tmp_path / "current"
    current.mkdir()
    _install_model(monkeypatch, current)
    before = h.model_stat_signature(current)
    model = current / "model.joblib"
    model.touch()
    touched = h.model_stat_signature(current)
    assert touched["mtime_ns"] >= before["mtime_ns"]
    replacement = tmp_path / "replacement"
    replacement.mkdir()
    replacement_model = replacement / "model.joblib"
    replacement_model.write_bytes(model.read_bytes())
    (replacement / "metadata.json").write_bytes((current / "metadata.json").read_bytes())
    (replacement / "manifest.json").write_bytes((current / "manifest.json").read_bytes())
    old = tmp_path / "old"
    current.rename(old)
    replacement.rename(current)
    swapped = h.model_stat_signature(current)
    assert swapped["size"] == before["size"]
    assert swapped["inode"] != before["inode"]
