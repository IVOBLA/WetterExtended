import json
import stat
import zipfile


def _patch_paths(monkeypatch, tmp_path):
    import ml_reset
    base = tmp_path / "train_data"
    monkeypatch.setattr(ml_reset, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ml_reset, "TRAIN_DATA_DIR", base)
    monkeypatch.setattr(ml_reset, "BACKUP_DIR", base / "backups")
    monkeypatch.setattr(ml_reset, "ARCHIVE_DIR", base / "archived_training_sources")
    monkeypatch.setattr(ml_reset, "STATUS_FILE", base / "ml_reset_status.json")
    monkeypatch.setattr(ml_reset, "SAVE_PATHS", {
        "models": str(base / "models"),
        "dataset": str(base / "dataset"),
        "objects": str(base / "objects"),
        "weather": str(base / "weather"),
    })
    return ml_reset, base


def _seed(base):
    for d in ["models/v_1", "models/current", "dataset", "objects", "weather", "hydro/static", "statistics"]:
        (base / d).mkdir(parents=True, exist_ok=True)
    (base / "models/v_1/model.txt").write_text("model")
    (base / "models/current/scaler_X.joblib").write_text("scaler")
    (base / "models/current/training_meta.json").write_text("{}")
    (base / "dataset/dataset.npz").write_text("dataset")
    (base / "dataset/tabular.parquet").write_text("tabular")
    (base / "objects/2026-01-01_00-00-00.json").write_text("[]")
    (base / "weather/2026-01-01_00-00-00.json").write_text("[]")
    (base / "runtime_overrides.json").write_text('{"keep": true}')
    (base / "hydro/static/catchments.json").write_text("{}")
    (base / "statistics/stats_2026.json").write_text("{}")


def test_backup_is_valid_and_complete(monkeypatch, tmp_path):
    ml_reset, base = _patch_paths(monkeypatch, tmp_path)
    _seed(base)
    backup = ml_reset.create_backup("models_only")
    path = tmp_path / backup["path"]
    assert path.exists() and path.stat().st_size > 0
    validation = ml_reset.validate_backup(path)
    assert validation["valid"], validation
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
    assert "manifest.json" in names
    assert "train_data/models/v_1/model.txt" in names
    assert "train_data/dataset/dataset.npz" in names
    assert "train_data/objects/2026-01-01_00-00-00.json" in names
    assert "train_data/weather/2026-01-01_00-00-00.json" in names
    assert "train_data/hydro/static/catchments.json" in names
    assert "train_data/runtime_overrides.json" in names


def test_models_only_reset_removes_artifacts_but_keeps_raw_and_config(monkeypatch, tmp_path):
    ml_reset, base = _patch_paths(monkeypatch, tmp_path)
    _seed(base)
    result = ml_reset.reset_ml("models_only")
    assert result["ok"] is True
    assert not (base / "models/v_1/model.txt").exists()
    assert not (base / "dataset/dataset.npz").exists()
    assert (base / "objects/2026-01-01_00-00-00.json").exists()
    assert (base / "weather/2026-01-01_00-00-00.json").exists()
    assert (base / "runtime_overrides.json").exists()
    assert (base / "hydro/static/catchments.json").exists()


def test_factory_reset_archives_training_sources_only(monkeypatch, tmp_path):
    ml_reset, base = _patch_paths(monkeypatch, tmp_path)
    _seed(base)
    ml_reset.reset_ml("full_new_data_only")
    assert not (base / "objects/2026-01-01_00-00-00.json").exists()
    assert not (base / "weather/2026-01-01_00-00-00.json").exists()
    assert list((base / "archived_training_sources").glob("*/objects/2026-01-01_00-00-00.json"))
    assert list((base / "archived_training_sources").glob("*/weather/2026-01-01_00-00-00.json"))
    assert (base / "runtime_overrides.json").exists()
    assert (base / "hydro/static/catchments.json").exists()
    status = json.loads((base / "ml_reset_status.json").read_text())
    assert status["next_action"] == "collect_new_data"


def test_backup_preserves_current_model_symlink(monkeypatch, tmp_path):
    ml_reset, base = _patch_paths(monkeypatch, tmp_path)
    (base / "models/v_1").mkdir(parents=True)
    (base / "models/v_1/model.txt").write_text("model")
    (base / "models/current").symlink_to("v_1", target_is_directory=True)

    backup = ml_reset.create_backup("models_only")
    path = tmp_path / backup["path"]

    with zipfile.ZipFile(path) as zf:
        current = zf.getinfo("train_data/models/current")
        mode = current.external_attr >> 16
        assert stat.S_ISLNK(mode)
        assert zf.read("train_data/models/current").decode("utf-8") == "v_1"
        assert "train_data/models/current/" not in zf.namelist()
