import json
import os
import time
from pathlib import Path

import pytest

import ml_reset


def _patch_paths(monkeypatch, tmp_path):
    root = tmp_path
    td = root / "train_data"
    monkeypatch.setattr(ml_reset, "PROJECT_ROOT", root)
    monkeypatch.setattr(ml_reset, "TRAIN_DATA_DIR", td)
    monkeypatch.setattr(ml_reset, "BACKUP_DIR", root / "backups")
    monkeypatch.setattr(ml_reset, "ARCHIVE_DIR", td / "archived_training_sources")
    monkeypatch.setattr(ml_reset, "STATUS_FILE", td / "ml_reset_status.json")
    monkeypatch.setattr(ml_reset, "BACKUP_STATUS_FILE", td / "ml_backup_status.json")
    monkeypatch.setattr(ml_reset, "ML_JOB_LOCK_FILE", td / "ml_job.lock")
    monkeypatch.setattr(ml_reset, "SAVE_PATHS", {
        "models": str(td / "models"),
        "dataset": str(td / "dataset"),
        "objects": str(td / "objects"),
        "weather": str(td / "weather"),
    })
    td.mkdir(parents=True, exist_ok=True)
    return root, td


def _file(path: Path, content="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_ml_reset_preview_counts_recursive(monkeypatch, tmp_path):
    root, td = _patch_paths(monkeypatch, tmp_path)
    _file(td / "dataset" / "a" / "b" / "one.json", "1234")
    _file(td / "dataset" / "two.npz", "12")
    plan = ml_reset.build_reset_plan("full_new_data_only")
    ds = next(s for s in plan["delete_sections"] if s["area"] == "dataset")
    assert ds["files"] == 2
    assert ds["dirs"] == 2
    assert ds["bytes"] == 6
    assert any("train_data/dataset/a/b/one.json" in e for e in ds["examples"])


def test_ml_reset_full_new_data_archives_objects_weather(monkeypatch, tmp_path):
    root, td = _patch_paths(monkeypatch, tmp_path)
    _file(td / "objects" / "old.json")
    _file(td / "weather" / "nested" / "old.json")
    result = ml_reset.reset_ml("full_new_data_only")
    assert (td / "objects").is_dir() and not any((td / "objects").iterdir())
    assert (td / "weather").is_dir() and not any((td / "weather").iterdir())
    assert list((td / "archived_training_sources").glob("*/objects/old.json"))
    assert list((td / "archived_training_sources").glob("*/weather/nested/old.json"))
    assert result["reset"]["archived_counts"]["files"] == 2


def test_ml_reset_does_not_delete_hydro_statistics_runtime_overrides(monkeypatch, tmp_path):
    root, td = _patch_paths(monkeypatch, tmp_path)
    _file(td / "hydro" / "h.json")
    _file(td / "statistics" / "s.json")
    _file(root / "runtime_overrides.json", '{"keep": true}')
    ml_reset.reset_ml("full_new_data_only")
    assert (td / "hydro" / "h.json").exists()
    assert (td / "statistics" / "s.json").exists()
    assert (root / "runtime_overrides.json").exists()


def test_ml_reset_start_returns_202_without_running_reset_inline(monkeypatch, tmp_path):
    root, td = _patch_paths(monkeypatch, tmp_path)
    called = {"inline": False}
    class DummyProcess:
        pid = 424242
        def __init__(self, target, args, daemon=False):
            self.target = target
        def start(self):
            pass
    class DummyCtx:
        Process = DummyProcess
    monkeypatch.setattr(ml_reset.multiprocessing, "get_context", lambda name: DummyCtx())
    monkeypatch.setattr(ml_reset, "_training_running", lambda: False)
    data = ml_reset.start_reset_background("models_only")
    assert data["started"] is True
    assert data["status"] == "running"
    assert not called["inline"]
    assert json.loads((td / "ml_reset_status.json").read_text())["pid"] == 424242


def test_ml_reset_status_reports_failed_when_pid_gone(monkeypatch, tmp_path):
    root, td = _patch_paths(monkeypatch, tmp_path)
    ml_reset._write_json(td / "ml_reset_status.json", {"status": "running", "running": True, "pid": 987654, "job_id": "x"})
    st = ml_reset.reset_job_status()
    assert st["failed"] is True
    assert st["status"] == "failed"


def test_ml_reset_lock_rejects_parallel_training_or_backup(monkeypatch, tmp_path):
    root, td = _patch_paths(monkeypatch, tmp_path)
    ml_reset._write_json(td / "ml_job.lock", {"kind": "backup", "job_id": "b", "pid": os.getpid()})
    with pytest.raises(RuntimeError):
        ml_reset.start_reset_background("models_only")
    (td / "ml_job.lock").unlink()
    monkeypatch.setattr(ml_reset, "_training_running", lambda: True)
    with pytest.raises(RuntimeError):
        ml_reset.start_reset_background("models_only")


def test_ml_reset_symlink_not_followed(monkeypatch, tmp_path):
    root, td = _patch_paths(monkeypatch, tmp_path)
    outside = tmp_path / "outside"
    _file(outside / "secret.txt", "secret")
    (td / "dataset").mkdir()
    (td / "dataset" / "link").symlink_to(outside, target_is_directory=True)
    plan = ml_reset.build_reset_plan("models_only")
    ds = next(s for s in plan["delete_sections"] if s["area"] == "dataset")
    assert ds["files"] == 1
    assert ds["dirs"] == 0
    assert (outside / "secret.txt").exists()


def test_ml_reset_result_contains_counts_bytes_and_paths(monkeypatch, tmp_path):
    root, td = _patch_paths(monkeypatch, tmp_path)
    _file(td / "models" / "m.bin", "123")
    _file(td / "dataset" / "d.bin", "12345")
    res = ml_reset.reset_ml("models_only")
    counts = res["reset"]["deleted_counts"]
    assert counts["files"] == 2
    assert counts["bytes"] == 8
    assert all("path" in s and "bytes" in s for s in counts["sections"])
