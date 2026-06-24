import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import importlib
import pytest

pytest.importorskip("flask")
app_module = importlib.import_module("app")


def _write_meta(models: Path, version: str, status="promoted", mae=4.0, kin=5.0):
    d = models / version
    d.mkdir(parents=True, exist_ok=True)
    meta = {
        "version": version,
        "timestamp_utc": f"2026-06-24T00:00:00Z-{version}",
        "status": status,
        "validation": {
            "status": status,
            "mae_old": 6.0,
            "mae_new": mae,
            "kin_baseline_mae": kin,
            "mae_by_horizon_old": {"10": 6.0},
            "mae_by_horizon_new": {"10": mae},
            "kin_baseline_by_horizon": {"10": kin},
            "samples_recent": 60,
            "samples_required": 50,
            "samples_missing": 0,
            "low_confidence": False,
        },
        "dataset": {"total_samples": 100, "train_samples": 80, "holdout_samples": 20},
        "horizons_trained": [10],
        "feature_count": 12,
    }
    (d / "training_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return d


def _client_with_models(monkeypatch, tmp_path):
    models = tmp_path / "train_data" / "models"
    models.mkdir(parents=True)
    monkeypatch.setitem(app_module.SAVE_PATHS, "models", str(models))
    return app_module.app.test_client(), models


def test_progress_marks_current_target_as_only_active(monkeypatch, tmp_path):
    client, models = _client_with_models(monkeypatch, tmp_path)
    _write_meta(models, "v_old", status="promoted")
    current_target = _write_meta(models, "v_x", status="promoted")
    (models / "current").symlink_to(current_target, target_is_directory=True)

    data = client.get("/api/progress").get_json()

    assert data["active_version"] == "v_x"
    active_rows = [v for v in data["versions"] if v["is_active"]]
    assert len(active_rows) == 1
    assert active_rows[0]["version_id"] == "v_x"
    assert data["active_meta"]["version_id"] == "v_x"


def test_rejected_below_kinematic_baseline_contains_baseline_and_clear_reason(monkeypatch, tmp_path):
    client, models = _client_with_models(monkeypatch, tmp_path)
    _write_meta(models, "v_bad", status="rejected_below_kinematic_baseline", mae=7.0, kin=5.0)

    row = client.get("/api/progress").get_json()["versions"][0]

    assert row["validation"]["kin_baseline_mae"] == 5.0
    assert "kinematische Baseline" in row["status_reason"]
    assert "schlechter" in row["status_reason"]


def test_promoted_is_not_current_when_current_points_elsewhere(monkeypatch, tmp_path):
    client, models = _client_with_models(monkeypatch, tmp_path)
    _write_meta(models, "v_promoted_old", status="promoted")
    current_target = _write_meta(models, "v_current", status="promoted")
    (models / "current").symlink_to(current_target, target_is_directory=True)

    rows = {v["version_id"]: v for v in client.get("/api/progress").get_json()["versions"]}

    assert rows["v_promoted_old"]["status"] == "promoted"
    assert rows["v_promoted_old"]["is_active"] is False
    assert rows["v_current"]["is_active"] is True


def test_missing_or_broken_current_is_handled_robustly(monkeypatch, tmp_path):
    client, models = _client_with_models(monkeypatch, tmp_path)
    _write_meta(models, "v_orphan", status="promoted")

    data_missing = client.get("/api/progress").get_json()
    assert data_missing["active_version"] is None
    assert data_missing["versions"][0]["is_active"] is False

    (models / "current").symlink_to(models / "does_not_exist", target_is_directory=True)
    data_broken = client.get("/api/progress").get_json()
    assert data_broken["active_version"] is None
    assert data_broken["versions"][0]["is_active"] is False
