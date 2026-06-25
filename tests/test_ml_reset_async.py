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


def _section_by_path(plan, path):
    for key in ["delete_sections", "preserve_sections", "managed_sections", "manual_review_sections", "protected_sections"]:
        for section in plan.get(key, []):
            if section.get("path") == path:
                return section
    raise AssertionError(f"section not found: {path}")


def test_ml_reset_classifies_cell_lineage_for_delete(monkeypatch, tmp_path):
    _root, td = _patch_paths(monkeypatch, tmp_path)
    _file(td / "cell_lineage" / "old.json")
    plan = ml_reset.build_reset_plan("full_new_data_only")
    assert _section_by_path(plan, "train_data/cell_lineage")["action"] == "delete_after_backup"


def test_ml_reset_classifies_hydro_live_for_delete(monkeypatch, tmp_path):
    _root, td = _patch_paths(monkeypatch, tmp_path)
    _file(td / "hydro" / "live" / "old.json")
    plan = ml_reset.build_reset_plan("full_new_data_only")
    assert _section_by_path(plan, "train_data/hydro/live")["action"] == "delete_after_backup"


def test_ml_reset_keeps_hydro_static(monkeypatch, tmp_path):
    _root, td = _patch_paths(monkeypatch, tmp_path)
    _file(td / "hydro" / "static" / "stations.json")
    plan = ml_reset.build_reset_plan("full_new_data_only")
    assert _section_by_path(plan, "train_data/hydro/static")["action"] == "preserve_static_reference"


@pytest.mark.parametrize("name", ["lightning", "wind", "system", "size_labels"])
def test_ml_reset_classifies_known_dynamic_for_delete(monkeypatch, tmp_path, name):
    _root, td = _patch_paths(monkeypatch, tmp_path)
    _file(td / name / "old.json")
    plan = ml_reset.build_reset_plan("full_new_data_only")
    assert _section_by_path(plan, f"train_data/{name}")["action"] == "delete_after_backup"


def test_ml_reset_classifies_lightning_for_delete(monkeypatch, tmp_path):
    test_ml_reset_classifies_known_dynamic_for_delete(monkeypatch, tmp_path, "lightning")


def test_ml_reset_classifies_wind_for_delete(monkeypatch, tmp_path):
    test_ml_reset_classifies_known_dynamic_for_delete(monkeypatch, tmp_path, "wind")


def test_ml_reset_classifies_system_for_delete(monkeypatch, tmp_path):
    test_ml_reset_classifies_known_dynamic_for_delete(monkeypatch, tmp_path, "system")


def test_ml_reset_classifies_size_labels_for_delete(monkeypatch, tmp_path):
    test_ml_reset_classifies_known_dynamic_for_delete(monkeypatch, tmp_path, "size_labels")


def test_ml_reset_keeps_install_backups(monkeypatch, tmp_path):
    _root, td = _patch_paths(monkeypatch, tmp_path)
    _file(td / "install_backups" / "installer.zip")
    plan = ml_reset.build_reset_plan("full_new_data_only")
    assert _section_by_path(plan, "train_data/install_backups")["action"] == "preserve_backup"
    ml_reset.reset_ml("full_new_data_only")
    assert (td / "install_backups" / "installer.zip").exists()


def test_ml_reset_warns_install_backups_inside_train_data(monkeypatch, tmp_path):
    _root, td = _patch_paths(monkeypatch, tmp_path)
    _file(td / "install_backups" / "installer.zip")
    plan = ml_reset.build_reset_plan("full_new_data_only")
    assert any("train_data/install_backups" in w for w in plan["warnings"])


def test_ml_reset_keeps_runtime_overrides_bak_and_lock(monkeypatch, tmp_path):
    _root, td = _patch_paths(monkeypatch, tmp_path)
    _file(td / "runtime_overrides.json.bak", "{}")
    _file(td / "runtime_overrides.json.lock", "lock")
    plan = ml_reset.build_reset_plan("full_new_data_only")
    assert _section_by_path(plan, "train_data/runtime_overrides.json.bak")["action"] == "preserve_config"
    assert _section_by_path(plan, "train_data/runtime_overrides.json.lock")["action"] == "preserve_config"
    ml_reset.reset_ml("full_new_data_only")
    assert (td / "runtime_overrides.json.bak").exists()
    assert (td / "runtime_overrides.json.lock").exists()


def test_ml_reset_status_files_do_not_block(monkeypatch, tmp_path):
    _root, td = _patch_paths(monkeypatch, tmp_path)
    _file(td / "ml_backup_status.json", "{}")
    _file(td / "ml_reset_status.json", "{}")
    plan = ml_reset.build_reset_plan("full_new_data_only")
    assert not plan["manual_review_sections"]
    assert _section_by_path(plan, "train_data/ml_backup_status.json")["action"] == "delete_runtime_status"


def test_ml_reset_manages_ml_reset_status_file(monkeypatch, tmp_path):
    _root, td = _patch_paths(monkeypatch, tmp_path)
    _file(td / "ml_reset_status.json", "{}")
    plan = ml_reset.build_reset_plan("full_new_data_only")
    assert _section_by_path(plan, "train_data/ml_reset_status.json")["action"] == "managed_by_reset_job"
    ml_reset.reset_ml("full_new_data_only")
    status = json.loads((td / "ml_reset_status.json").read_text())
    assert status["verification"]["verification_status"] == "passed"


def test_ml_reset_no_manual_review_for_known_paths(monkeypatch, tmp_path):
    _root, td = _patch_paths(monkeypatch, tmp_path)
    for path in ["cell_lineage/x", "hydro/live/x", "install_backups/x", "lightning/x", "size_labels/x", "system/x", "wind/x"]:
        _file(td / path)
    for name in ["ml_backup_status.json", "ml_reset_status.json", "runtime_overrides.json.bak", "runtime_overrides.json.lock"]:
        _file(td / name, "{}")
    plan = ml_reset.build_reset_plan("full_new_data_only")
    assert plan["manual_review_sections"] == []


def test_ml_reset_still_blocks_truly_unknown_path(monkeypatch, tmp_path):
    _root, td = _patch_paths(monkeypatch, tmp_path)
    _file(td / "mystery" / "x")
    plan = ml_reset.build_reset_plan("full_new_data_only")
    assert any(s["path"] == "train_data/mystery" for s in plan["manual_review_sections"])
    with pytest.raises(ValueError):
        ml_reset.start_reset_background("full_new_data_only")


def test_ml_reset_verifies_known_dynamic_paths_deleted(monkeypatch, tmp_path):
    _root, td = _patch_paths(monkeypatch, tmp_path)
    for path in ["cell_lineage/x", "hydro/live/x", "lightning/x", "size_labels/x", "system/x", "wind/x"]:
        _file(td / path)
    result = ml_reset.reset_ml("full_new_data_only")
    assert result["reset"]["verification"]["verification_status"] == "passed"
    assert all(not (td / p).exists() for p in ["cell_lineage", "hydro/live", "lightning", "size_labels", "system", "wind"])


def test_ml_reset_verifies_known_preserved_paths_still_exist(monkeypatch, tmp_path):
    root, td = _patch_paths(monkeypatch, tmp_path)
    for path in ["install_backups/x", "runtime_overrides.json.bak", "runtime_overrides.json.lock", "hydro/static/x", "statistics/x", "dem/x", "cell_filters/x"]:
        _file(td / path, "{}")
    _file(root / "backups" / "keep.zip")
    result = ml_reset.reset_ml("full_new_data_only")
    verified = {s["path"]: s["ok"] for s in result["reset"]["verification"]["preserved_sections_verified"]}
    for path in ["train_data/install_backups", "train_data/runtime_overrides.json.bak", "train_data/runtime_overrides.json.lock", "train_data/hydro/static", "train_data/statistics", "train_data/dem", "train_data/cell_filters", "backups"]:
        assert verified[path] is True
