"""B496: Verwaiste lokale Analyse-Laeufe erkennen und sichtbar machen."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from tools import run_local_analysis as runner


def _started_ago(seconds: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _runner_config(tmp_path, timeout_s=10):
    return {
        "timeout_s": timeout_s,
        "status_path": "status.json",
        "log_path": "run.log",
        "result_path": "result.json",
        "allowed_tools": "Read",
    }


def _prepare_dry_run(monkeypatch, tmp_path, cfg):
    monkeypatch.setattr(runner, "load_config", lambda _repo: cfg)
    monkeypatch.setattr(runner, "load_mode", lambda _repo: ("local", ""))
    monkeypatch.setattr(runner, "run_deterministic_ai_checks", lambda _repo: None)
    monkeypatch.setattr(runner, "_source_snapshot_id", lambda _repo: "snapshot")
    monkeypatch.setattr(runner, "_git_commit", lambda _repo: "commit")
    monkeypatch.setattr(
        runner, "check_preconditions",
        lambda _cfg, _repo: ("/usr/bin/claude", "Auftrag", tmp_path / "settings.json"),
    )


def test_stale_running_entry_is_closed_before_dry_run(tmp_path, monkeypatch):
    cfg = _runner_config(tmp_path)
    status_path = tmp_path / "status.json"
    status_path.write_text(json.dumps({
        "state": "running", "mode": "local", "run_started_at_utc": _started_ago(30),
        "attempts_today": 2, "last_success_date": "2026-08-01",
    }), encoding="utf-8")
    _prepare_dry_run(monkeypatch, tmp_path, cfg)

    assert runner.main(["--repo-dir", str(tmp_path), "--dry-run"]) == 0
    recovered = runner.read_json_quiet(status_path)
    assert recovered["state"] == "failed"
    assert "vermutlich hart beendet" in recovered["error"]
    assert recovered["attempts_today"] == 2
    assert recovered["last_success_date"] == "2026-08-01"


def test_fresh_running_entry_is_not_changed(tmp_path, monkeypatch):
    cfg = _runner_config(tmp_path)
    status_path = tmp_path / "status.json"
    previous = {
        "state": "running", "mode": "local", "run_started_at_utc": _started_ago(5),
        "attempts_today": 1,
    }
    status_path.write_text(json.dumps(previous), encoding="utf-8")
    _prepare_dry_run(monkeypatch, tmp_path, cfg)

    assert runner.main(["--repo-dir", str(tmp_path), "--dry-run"]) == 0
    assert runner.read_json_quiet(status_path) == previous


@pytest.mark.parametrize(("age_s", "expected_stale"), [(30, True), (5, False)])
def test_status_api_reports_service_and_staleness(tmp_path, monkeypatch, age_s, expected_stale):
    pytest.importorskip("flask")
    import app as app_module

    status_path = tmp_path / "status.json"
    status_path.write_text(json.dumps({
        "state": "running", "run_started_at_utc": _started_ago(age_s),
    }), encoding="utf-8")
    cfg = _runner_config(tmp_path)
    monkeypatch.setattr(
        app_module.runtime_config, "get",
        lambda key, default=None: cfg if key == "LOCAL_ANALYSIS_CONFIG" else default,
    )
    monkeypatch.setattr(
        app_module, "_analysis_mode_effective", lambda: ("local", ""),
    )
    monkeypatch.setattr(
        app_module, "_local_analysis_module",
        lambda: type("LocalAnalysis", (), {"resolve_claude_bin": staticmethod(lambda _cfg: "/bin/claude")}),
    )
    monkeypatch.setattr(
        subprocess, "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout="active\n", stderr=""),
    )

    with app_module.app.app_context():
        payload = app_module.api_local_analysis_status().get_json()

    assert payload["service_state"] == "active"
    assert payload["run_stale"] is expected_stale
