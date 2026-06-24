import json
import zipfile
from pathlib import Path

import pytest

import debug_export
import drift_detector as dd


def test_manual_export_runs_diagnosis_and_zip_contains_file(tmp_path, monkeypatch):
    ev = tmp_path / "train_data" / "evaluation"
    ev.mkdir(parents=True)
    called = {}

    def fake_diag(*, hours, base_dir, save_paths):
        called["hours"] = hours
        out = Path(save_paths["evaluation"]) / "forecast_quality_diagnosis_latest.json"
        out.write_text(json.dumps({"status": "ok", "checked_at_utc": "2026-06-24T00:00:00Z"}), encoding="utf-8")
        return {"status": "ok", "path": str(out)}

    monkeypatch.setattr(debug_export, "run_forecast_quality_diagnosis_before_export", fake_diag)
    z, _, _ = debug_export.create_debug_export_zip(base_dir=tmp_path, save_paths={"evaluation": str(ev)}, hours=24)
    try:
        names = zipfile.ZipFile(z).namelist()
        assert called["hours"] == 24
        assert any(n.endswith("evaluation/forecast_quality_diagnosis_latest.json") for n in names)
    finally:
        z.unlink(missing_ok=True)


def test_automatic_export_runs_diagnosis_and_git_export_contains_file(tmp_path, monkeypatch):
    from tools import publish_latest_debug_export_branch as pub

    repo = tmp_path / "repo"
    repo.mkdir()
    ev = repo / "train_data" / "evaluation"
    ev.mkdir(parents=True)
    diag = ev / "forecast_quality_diagnosis_latest.json"
    diag.write_text('{"status":"ok"}', encoding="utf-8")
    part = tmp_path / "export.zip"
    with zipfile.ZipFile(part, "w") as zf:
        zf.writestr("evaluation/forecast_quality_diagnosis_latest.json", '{"status":"ok"}')

    commands = []
    monkeypatch.setattr(pub, "run_git", lambda cmd, cwd, check=True: commands.append((cmd, Path(cwd))) or type("R", (), {"stdout": "abc\n", "returncode": 0, "stderr": ""})())
    manifest = pub.write_branch_repo(
        temp_repo=tmp_path / "branch",
        source_zip=[(part, "wetterextended_debug1.zip")],
        source_filename="wetterextended_debug1.zip",
        export_manifest={"forecast_quality_diagnosis": {"status": "ok"}},
        repo_dir=repo,
        branch="debug-export-latest",
        target_path=pub.validate_relative_path(pub.DEFAULT_TARGET_PATH),
        hours=24,
        max_source_total_mb=512,
        max_zip_mb=90,
        zip_size_bytes=part.stat().st_size,
    )
    assert (tmp_path / "branch" / "evaluation" / "forecast_quality_diagnosis_latest.json").exists()
    assert manifest["export_manifest"]["forecast_quality_diagnosis"]["status"] == "ok"


def test_diagnosis_error_does_not_block_export_and_error_file_in_zip(tmp_path, monkeypatch):
    ev = tmp_path / "train_data" / "evaluation"
    ev.mkdir(parents=True)

    def fake_diag(*, hours, base_dir, save_paths):
        out = Path(save_paths["evaluation"]) / "forecast_quality_diagnosis_error.json"
        out.write_text(json.dumps({"status": "error", "error": "boom", "traceback": "tb", "timestamp_utc": "2026-06-24T00:00:00Z"}), encoding="utf-8")
        return {"status": "error", "error": "boom"}

    monkeypatch.setattr(debug_export, "run_forecast_quality_diagnosis_before_export", fake_diag)
    z, _, manifest = debug_export.create_debug_export_zip(base_dir=tmp_path, save_paths={"evaluation": str(ev)}, hours=24)
    try:
        assert manifest["forecast_quality_diagnosis"]["status"] == "error"
        assert any(n.endswith("evaluation/forecast_quality_diagnosis_error.json") for n in zipfile.ZipFile(z).namelist())
    finally:
        z.unlink(missing_ok=True)


def _history(now, baseline, recent):
    old = (now - dd.timedelta(hours=25)).isoformat().replace("+00:00", "Z")
    new = (now - dd.timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    return ([{"timestamp_utc": old, "horizons": [{"horizon": 10, "mae_km": baseline}]}] * 3 +
            [{"timestamp_utc": new, "horizons": [{"horizon": 10, "mae_km": recent}]}] * 3)


def test_drift_mail_not_sent_when_model_improves(monkeypatch):
    now = dd.datetime.now(dd.timezone.utc)
    sent = []
    monkeypatch.setattr(dd, "_read_history", lambda: _history(now, 20, 11))
    monkeypatch.setattr(dd, "_has_ml_model", lambda: True)
    monkeypatch.setattr(dd, "DRIFT_MAE_THRESHOLD_KM", 2.0)
    monkeypatch.setattr("email_notifier.send_drift_alert", lambda status: sent.append(status))
    status = dd.check_and_alert()
    assert status["drift_detected"] is False
    assert sent == []


def test_drift_mail_sent_on_real_drift(monkeypatch):
    now = dd.datetime.now(dd.timezone.utc)
    sent = []
    monkeypatch.setattr(dd, "_read_history", lambda: _history(now, 10, 15))
    monkeypatch.setattr(dd, "_has_ml_model", lambda: True)
    monkeypatch.setattr(dd, "DRIFT_MAE_THRESHOLD_KM", 2.0)
    monkeypatch.setattr("email_notifier.send_drift_alert", lambda status: sent.append(status))
    status = dd.check_and_alert()
    assert status["drift_detected"] is True
    assert len(sent) == 1
