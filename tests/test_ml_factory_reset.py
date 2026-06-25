import json
import stat
import time
import zipfile

import pytest


def _patch_paths(monkeypatch, tmp_path):
    import ml_reset
    base = tmp_path / "train_data"
    monkeypatch.setattr(ml_reset, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ml_reset, "TRAIN_DATA_DIR", base)
    monkeypatch.setattr(ml_reset, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(ml_reset, "ARCHIVE_DIR", base / "archived_training_sources")
    monkeypatch.setattr(ml_reset, "STATUS_FILE", base / "ml_reset_status.json")
    monkeypatch.setattr(ml_reset, "BACKUP_STATUS_FILE", base / "ml_backup_status.json")
    monkeypatch.setattr(ml_reset, "ML_JOB_LOCK_FILE", base / "ml_job.lock")
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
    assert path.parent == tmp_path / "backups"
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


def test_backup_excludes_legacy_train_data_backups(monkeypatch, tmp_path):
    ml_reset, base = _patch_paths(monkeypatch, tmp_path)
    _seed(base)
    legacy_backup = base / "backups/20260101_000000_train_data.zip"
    legacy_backup.parent.mkdir(parents=True)
    legacy_backup.write_text("old")

    backup = ml_reset.create_backup("models_only")
    path = tmp_path / backup["path"]

    assert path.parent == tmp_path / "backups"
    assert not legacy_backup.exists()
    assert (tmp_path / "backups/20260101_000000_train_data.zip").exists()
    with zipfile.ZipFile(path) as zf:
        assert not any(name.startswith("train_data/backups/") for name in zf.namelist())


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


def test_backup_records_problematic_symlink_without_failing(monkeypatch, tmp_path):
    ml_reset, base = _patch_paths(monkeypatch, tmp_path)
    (base / "models/current").mkdir(parents=True)
    (base / "models/current/model.txt").write_text("model")
    (base / "models/current/v_bootstrap").symlink_to("v_bootstrap")

    backup = ml_reset.create_backup("models_only")
    path = tmp_path / backup["path"]

    assert backup["valid"] is True
    with zipfile.ZipFile(path) as zf:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        loop_link = zf.getinfo("train_data/models/current/v_bootstrap")
        mode = loop_link.external_attr >> 16
        assert stat.S_ISLNK(mode)
    assert "train_data/models/current/v_bootstrap" in manifest["skipped_entries"]
    assert manifest["symlink_warnings"]


def test_delete_backup_only_removes_root_backup_zip(monkeypatch, tmp_path):
    ml_reset, _base = _patch_paths(monkeypatch, tmp_path)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    backup_path = backup_dir / "20260101_000000_train_data.zip"
    with zipfile.ZipFile(backup_path, "w") as zf:
        zf.writestr("manifest.json", "{}")

    ml_reset.delete_backup(backup_path.name)

    assert not backup_path.exists()


def test_delete_backup_blocks_path_traversal(monkeypatch, tmp_path):
    ml_reset, base = _patch_paths(monkeypatch, tmp_path)
    base.mkdir(parents=True, exist_ok=True)
    protected = base / "runtime_overrides.json"
    protected.write_text('{"keep": true}')

    with pytest.raises(ValueError):
        ml_reset.delete_backup("../train_data/runtime_overrides.json")

    assert protected.exists()


def test_manual_backup_starts_background_and_reports_status(monkeypatch, tmp_path):
    ml_reset, base = _patch_paths(monkeypatch, tmp_path)
    _seed(base)

    result = ml_reset.start_backup_background("manual")

    assert result["started"] is True
    assert result["status"] == "running"
    status = {}
    for _ in range(50):
        status = ml_reset.backup_job_status()
        if status.get("finished") or status.get("failed"):
            break
        time.sleep(0.1)
    assert status["finished"] is True
    assert status["running"] is False
    assert status["backup"]["id"].endswith("_train_data.zip")


def test_fast_background_backup_does_not_recreate_released_lock(monkeypatch, tmp_path):
    ml_reset, base = _patch_paths(monkeypatch, tmp_path)
    _seed(base)

    class ImmediateProcess:
        pid = 424242

        def __init__(self, target, args=(), daemon=None):
            self._target = target
            self._args = args

        def start(self):
            self._target(*self._args)

    class ImmediateContext:
        Process = ImmediateProcess

    monkeypatch.setattr(ml_reset.multiprocessing, "get_context", lambda _method: ImmediateContext())

    result = ml_reset.start_backup_background("manual")

    assert result["started"] is True
    assert not ml_reset.ML_JOB_LOCK_FILE.exists()
    status = ml_reset.backup_job_status()
    assert status["finished"] is True
    assert status["running"] is False


def test_reset_blocked_while_backup_lock_exists(monkeypatch, tmp_path):
    ml_reset, _base = _patch_paths(monkeypatch, tmp_path)
    owner = ml_reset._acquire_ml_job_lock("backup", "test_backup")
    try:
        with pytest.raises(RuntimeError, match="ML-Job läuft bereits"):
            ml_reset.reset_ml("models_only")
    finally:
        ml_reset._release_ml_job_lock(owner)
