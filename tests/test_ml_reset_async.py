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


def test_ml_reset_full_new_data_deletes_objects_weather_models_dataset(monkeypatch, tmp_path):
    root, td = _patch_paths(monkeypatch, tmp_path)
    _file(td / "objects" / "old.json")
    _file(td / "weather" / "nested" / "old.json")
    result = ml_reset.reset_ml("full_new_data_only")
    assert (td / "objects").is_dir() and not any((td / "objects").iterdir())
    assert (td / "weather").is_dir() and not any((td / "weather").iterdir())
    assert not (td / "archived_training_sources" / "old.json").exists()
    assert result["reset"]["deleted_counts"]["files"] == 2


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


def test_ml_reset_full_new_data_deletes_arome_cape_cloud(monkeypatch, tmp_path):
    root, td = _patch_paths(monkeypatch, tmp_path)
    for name in ["arome", "cape", "cloud"]:
        _file(td / name / "old.bin")
    ml_reset.reset_ml("full_new_data_only")
    assert all(not (td / name).exists() for name in ["arome", "cape", "cloud"])


def test_ml_reset_full_new_data_deletes_evaluation(monkeypatch, tmp_path):
    root, td = _patch_paths(monkeypatch, tmp_path)
    _file(td / "evaluation" / "pending.json")
    ml_reset.reset_ml("full_new_data_only")
    assert not (td / "evaluation").exists()


def test_ml_reset_full_new_data_deletes_external_responses(monkeypatch, tmp_path):
    root, td = _patch_paths(monkeypatch, tmp_path)
    _file(td / "external_responses" / "arso_radar" / "old.json")
    ml_reset.reset_ml("full_new_data_only")
    assert not (td / "external_responses").exists()


def test_ml_reset_full_new_data_deletes_archived_training_sources(monkeypatch, tmp_path):
    root, td = _patch_paths(monkeypatch, tmp_path)
    _file(td / "archived_training_sources" / "old" / "objects" / "x.json")
    ml_reset.reset_ml("full_new_data_only")
    assert not (td / "archived_training_sources").exists()


def test_ml_reset_full_new_data_keeps_root_backups(monkeypatch, tmp_path):
    root, td = _patch_paths(monkeypatch, tmp_path)
    _file(root / "backups" / "keep.zip")
    ml_reset.reset_ml("full_new_data_only")
    assert (root / "backups" / "keep.zip").exists()


def test_ml_reset_full_new_data_keeps_statistics(monkeypatch, tmp_path):
    root, td = _patch_paths(monkeypatch, tmp_path)
    _file(td / "statistics" / "long.json")
    ml_reset.reset_ml("full_new_data_only")
    assert (td / "statistics" / "long.json").exists()


def test_ml_reset_full_new_data_keeps_config_files(monkeypatch, tmp_path):
    root, td = _patch_paths(monkeypatch, tmp_path)
    _file(root / ".env", "A=1")
    _file(root / "runtime_overrides.json", "{}")
    _file(td / "runtime_overrides.json", "{}")
    ml_reset.reset_ml("full_new_data_only")
    assert (root / ".env").exists() and (root / "runtime_overrides.json").exists() and (td / "runtime_overrides.json").exists()


def test_ml_reset_full_new_data_keeps_dem_cell_filters(monkeypatch, tmp_path):
    root, td = _patch_paths(monkeypatch, tmp_path)
    _file(td / "dem" / "grid.tif")
    _file(td / "cell_filters" / "cells.json")
    ml_reset.reset_ml("full_new_data_only")
    assert (td / "dem" / "grid.tif").exists() and (td / "cell_filters" / "cells.json").exists()


def test_ml_reset_full_new_data_keeps_hydro_static(monkeypatch, tmp_path):
    root, td = _patch_paths(monkeypatch, tmp_path)
    _file(td / "hydro" / "static" / "stations.json")
    ml_reset.reset_ml("full_new_data_only")
    assert (td / "hydro" / "static" / "stations.json").exists()


def test_ml_reset_full_new_data_deletes_hydro_dynamic_if_present(monkeypatch, tmp_path):
    root, td = _patch_paths(monkeypatch, tmp_path)
    _file(td / "hydro" / "measurements" / "old.json")
    ml_reset.reset_ml("full_new_data_only")
    assert not (td / "hydro" / "measurements").exists()


def test_ml_reset_preview_lists_every_train_data_child(monkeypatch, tmp_path):
    root, td = _patch_paths(monkeypatch, tmp_path)
    for name in ["arome", "unknown_staticish", "statistics"]:
        _file(td / name / "x")
    plan = ml_reset.build_reset_plan("full_new_data_only")
    listed = {s["path"] for key in ["delete_sections", "preserve_sections", "manual_review_sections", "delete_children_sections"] for s in plan[key]}
    assert {"train_data/arome", "train_data/unknown_staticish", "train_data/statistics"} <= listed


def test_ml_reset_preview_has_counts_for_every_section(monkeypatch, tmp_path):
    root, td = _patch_paths(monkeypatch, tmp_path)
    _file(td / "arome" / "x", "123")
    plan = ml_reset.build_reset_plan("full_new_data_only")
    for key in ["delete_sections", "preserve_sections", "manual_review_sections", "protected_sections"]:
        for sec in plan[key]:
            assert {"files", "dirs", "bytes", "size_mb", "examples", "reason", "will_recreate", "protected"} <= set(sec)


def test_ml_reset_refuses_if_protected_path_in_delete_plan(monkeypatch, tmp_path):
    root, td = _patch_paths(monkeypatch, tmp_path)
    plan = {"delete_sections": [{"path": "train_data/statistics", "action": "delete_after_backup"}], "delete_children_sections": []}
    with pytest.raises(RuntimeError):
        ml_reset._assert_delete_plan_safe(plan)


def test_ml_reset_requires_valid_backup_before_delete(monkeypatch, tmp_path):
    root, td = _patch_paths(monkeypatch, tmp_path)
    _file(td / "models" / "m.bin")
    monkeypatch.setattr(ml_reset, "validate_backup", lambda path: {"valid": False, "errors": ["broken"]})
    with pytest.raises(RuntimeError):
        ml_reset.reset_ml("full_new_data_only")
    assert (td / "models" / "m.bin").exists()


def test_ml_reset_status_reports_deleted_and_preserved_counts(monkeypatch, tmp_path):
    root, td = _patch_paths(monkeypatch, tmp_path)
    _file(td / "models" / "m.bin", "123")
    _file(td / "statistics" / "s.json")
    ml_reset.reset_ml("full_new_data_only")
    status = json.loads((td / "ml_reset_status.json").read_text())
    assert status["deleted_counts"]["files"] == 1
    assert any(s["path"] == "train_data/statistics" for s in status["preserved_sections"])


def test_ml_reset_preview_contains_summary_and_sections(monkeypatch, tmp_path):
    root, td = _patch_paths(monkeypatch, tmp_path)
    _file(td / "arome" / "old.json", "123")
    _file(td / "statistics" / "long.json", "12")
    plan = ml_reset.build_reset_plan("full_new_data_only")
    assert plan["backup"]["target_dir"] == "backups"
    assert any(s["path"] == "train_data/arome" for s in plan["sections"])
    assert plan["summary"]["delete_files"] >= 1
    assert plan["summary"]["preserve_files"] >= 1


def test_ml_reset_start_saves_execution_plan(monkeypatch, tmp_path):
    root, td = _patch_paths(monkeypatch, tmp_path)
    class DummyProcess:
        pid = 424243
        def __init__(self, target, args, daemon=False):
            self.target = target
        def start(self):
            pass
    class DummyCtx:
        Process = DummyProcess
    monkeypatch.setattr(ml_reset.multiprocessing, "get_context", lambda name: DummyCtx())
    monkeypatch.setattr(ml_reset, "_training_running", lambda: False)
    ml_reset.start_reset_background("full_new_data_only")
    status = json.loads((td / "ml_reset_status.json").read_text())
    assert status["execution_plan"]["mode"] == "full_new_data_only"


def test_ml_reset_verify_fails_when_leftovers_remain(monkeypatch, tmp_path):
    root, td = _patch_paths(monkeypatch, tmp_path)
    _file(td / "arome" / "old.json")
    plan = ml_reset.build_reset_plan("full_new_data_only")
    verification = ml_reset.verify_reset_result(plan)
    assert verification["verification_status"] == "leftovers"
    assert verification["leftovers_total"]["files"] == 1
