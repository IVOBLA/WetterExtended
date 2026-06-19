import json
import os
import time
from pathlib import Path

import pytest
import sys
import types

sys.modules.setdefault("cv2", types.SimpleNamespace())


def _configure_tmp(monkeypatch, tmp_path):
    import config
    import training_control
    models = tmp_path / "models"
    dataset = tmp_path / "dataset"
    models.mkdir()
    dataset.mkdir()
    monkeypatch.setitem(config.SAVE_PATHS, "models", str(models))
    monkeypatch.setitem(config.SAVE_PATHS, "dataset", str(dataset))
    monkeypatch.setattr(training_control, "SAVE_PATHS", config.SAVE_PATHS, raising=False)
    return models


def test_post_training_start_starts_background(monkeypatch, tmp_path):
    import training_control
    _configure_tmp(monkeypatch, tmp_path)
    called = []
    done = []

    def fake_run(run_id=None, source="manual"):
        called.append((run_id, source))
        training_control._update_status(running=False, run_id=run_id, last_status="success", progress_message="ok")
        done.append(True)

    monkeypatch.setattr(training_control, "run_training_with_lock", fake_run)
    started, data = training_control.start_training_background(source="manual")
    assert started is True
    assert data["started"] is True
    for _ in range(50):
        if done:
            break
        time.sleep(0.01)
    assert called and called[0][1] == "manual"


def test_post_training_start_conflict_when_lock_active(monkeypatch, tmp_path):
    import training_control
    models = _configure_tmp(monkeypatch, tmp_path)
    (models / "training.lock").write_text(json.dumps({"run_id": "r1", "pid": os.getpid(), "started_at": "now"}), encoding="utf-8")
    started, data = training_control.start_training_background(source="manual")
    assert started is False
    assert data["running"] is True


def test_get_training_status_running_and_failure(monkeypatch, tmp_path):
    import training_control
    models = _configure_tmp(monkeypatch, tmp_path)
    (models / "training.lock").write_text(json.dumps({"run_id": "r2", "pid": os.getpid(), "started_at": "now"}), encoding="utf-8")
    running = training_control.get_training_status()
    assert running["running"] is True
    assert running["run_id"] == "r2"
    (models / "training.lock").unlink()
    training_control._update_status(running=False, last_status="failed", last_error="boom")
    failed = training_control.get_training_status()
    assert failed["running"] is False
    assert failed["last_error"] == "boom"


def test_manual_training_uses_scheduler_pipeline_and_writes_meta(monkeypatch, tmp_path):
    import training_control
    _configure_tmp(monkeypatch, tmp_path)
    calls = []
    meta = {"version": "v_test", "validation": {"status": "promoted"}}
    sys.modules["model_training"] = types.SimpleNamespace(retrain_all=lambda: calls.append("retrain_all") or meta)
    sys.modules["severity_dataset"] = types.SimpleNamespace(build_severity_dataset=lambda: calls.append("severity_dataset") or {})
    sys.modules["severity_training"] = types.SimpleNamespace(train_severity_models=lambda: calls.append("severity_training") or {})
    result = training_control.run_training_with_lock(run_id="manual-test", source="manual")
    assert result["meta"] == meta
    assert calls == ["retrain_all", "severity_dataset", "severity_training"]
    assert training_control.get_training_status()["latest_training_meta"] == meta


def test_scheduler_uses_same_training_function():
    source = Path("scheduler.py").read_text(encoding="utf-8")
    assert "from training_control import run_training_with_lock" in source
    assert 'run_training_with_lock(source=f"scheduler:{job_name}")' in source


def test_stale_lock_is_removed(monkeypatch, tmp_path):
    import training_control
    models = _configure_tmp(monkeypatch, tmp_path)
    lock = models / "training.lock"
    lock.write_text(json.dumps({"run_id": "old", "pid": 999999999, "started_at": "old"}), encoding="utf-8")
    monkeypatch.setattr(training_control, "run_training_with_lock", lambda run_id=None, source="manual": None)
    assert training_control.start_training_background(source="manual")[0] is True
    status = training_control.get_training_status()
    assert status["run_id"] != "old"
