"""B470: Ein fehlgeschlagener Lauf muss lesbar sein."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "run_local_analysis.py"


@pytest.fixture
def runner(monkeypatch):
    spec = importlib.util.spec_from_file_location("run_local_analysis_b470", TOOL)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_plain_returncode(runner): assert "2" in runner.describe_returncode(2)
def test_sigkill_is_named_and_explained(runner):
    text = runner.describe_returncode(-9); assert "SIGKILL" in text; assert "Speichermangel" in text
def test_sigterm_is_named(runner): assert "SIGTERM" in runner.describe_returncode(-15)
def test_unknown_returncode_does_not_crash(runner): assert runner.describe_returncode(None)
def test_message_is_never_empty(runner):
    msg = runner.summarize_failure(2, "", ""); assert msg.strip(); assert "keine Ausgabe" in msg
def test_stderr_is_preferred(runner): assert "boom" in runner.summarize_failure(2, "egal", "boom")
def test_stdout_is_used_when_stderr_is_silent(runner): assert "kaputt" in runner.summarize_failure(2, '{"is_error": true, "result": "kaputt"}', "")
def test_signal_appears_in_the_message(runner): assert "SIGKILL" in runner.summarize_failure(-9, "", "")
def test_message_is_bounded(runner): assert len(runner.summarize_failure(2, "", "x" * 50000)) < 1000


def _log(runner, tmp_path, **over):
    args = dict(cmd=["/usr/bin/claude", "-p", "A" * 4000, "--output-format", "json"], claude_bin="", mode="local", rc=2, duration_s=398.2, stdout="OUT", stderr="ERR")
    args.update(over); target = tmp_path / "sub" / "run.log"; runner.write_run_log(target, **args)
    return target.read_text(encoding="utf-8")


def test_log_contains_the_essentials(runner, tmp_path):
    text = _log(runner, tmp_path)
    for needed in ("Zeitpunkt", "Betriebsart : local", "Dauer       : 398.2 s", "stdout", "stderr", "OUT", "ERR"): assert needed in text
def test_log_elides_the_prompt(runner, tmp_path):
    text = _log(runner, tmp_path); assert "A" * 100 not in text; assert "<Auftrag: 4000 Zeichen>" in text
def test_log_marks_empty_streams(runner, tmp_path): assert _log(runner, tmp_path, stdout="", stderr="").count("(leer)") == 2
def test_log_is_truncated(runner, tmp_path): assert len(_log(runner, tmp_path, stdout="x" * 100000)) < 20000
def test_log_creates_missing_directories(runner, tmp_path):
    target = tmp_path / "a" / "b" / "run.log"; runner.write_run_log(target, cmd=["c"], claude_bin="", mode="local", rc=0, duration_s=1.0); assert target.is_file()
def test_log_failure_never_breaks_the_run(runner): runner.write_run_log("/proc/unmoeglich/run.log", cmd=["c"], claude_bin="", mode="local", rc=0, duration_s=1.0)


@pytest.fixture
def silent_cli(tmp_path):
    binary = tmp_path / "claude"; binary.write_text('#!/bin/sh\n[ "$1" = "--version" ] && { echo "2.1.206"; exit 0; }\nexit 2\n', encoding="utf-8"); binary.chmod(0o755)
    (tmp_path / "docs").mkdir(); (tmp_path / "docs" / "p.md").write_text("Auftrag", encoding="utf-8")
    (tmp_path / "tools").mkdir(); (tmp_path / "tools" / "s.json").write_text(json.dumps({"permissions": {"deny": ["Read(**/.env*)"]}}), encoding="utf-8")
    return binary


def _config(binary):
    return {"cron_hour": 0, "cron_minute": 0, "timeout_s": 60, "max_turns": 5, "claude_bin": str(binary), "allowed_tools": "Read,Grep,Glob,Bash(python3 tools/ro_query.py *)", "prompt_path": "docs/p.md", "settings_path": "tools/s.json", "status_path": "status.json", "result_path": "result.json", "log_path": "run.log"}


def _git_init(tmp_path):
    """B502: main() ermittelt seit B502 git_commit/source_snapshot_id erst nach
    erfolgreicher Vorbedingungspruefung, braucht dafuer aber ein echtes Git-Repository —
    genau wie in der Produktionsumgebung, in der --repo-dir immer ein echtes Checkout ist."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.email=test@example.invalid", "-c", "user.name=Test",
                     "commit", "--allow-empty", "-q", "-m", "init"], cwd=tmp_path, check=True)


def test_silent_failure_leaves_a_readable_trace(runner, tmp_path, silent_cli, monkeypatch):
    _git_init(tmp_path)
    monkeypatch.setattr(runner, "load_mode", lambda repo_dir: ("local", "")); monkeypatch.setattr(runner, "load_config", lambda repo_dir: _config(silent_cli))
    assert runner.main(["--repo-dir", str(tmp_path), "--force"]) == 2
    status = json.loads((tmp_path / "status.json").read_text()); assert status["state"] == "failed"; assert status["rc"] == 2; assert "keine Ausgabe" in status["error"]; assert status["log_path"].endswith("run.log")
    log = (tmp_path / "run.log").read_text(); assert "Rueckgabewert 2" in log; assert "2.1.206" in log


# B516: alle fuenf P105-Bereiche sind seit B514 in jeder Antwort Pflicht
# (kein Default-Ausfuellen mehr) und tragen affected_horizons/expected_metric_change.
_B516_VALID_FINDING = {
    "current_quality": "unklar", "distance_to_target": None,
    "dominant_error_class": "unknown", "evidence": [],
    "last_attempted_improvement": None, "result": "plateau",
    "next_falsifiable_action": "Naechsten Export gegen denselben Gold-Snapshot messen",
    "eligible_for_autonomous_experiment": False,
    "affected_horizons": [],
    "expected_metric_change": {"metric": "mae_km", "direction": "unchanged", "minimum_change": 0.0},
}
_B516_FINDING_NAMES = ("verification_findings", "tracking_lineage_findings", "kinematic_findings",
                       "ml_model_findings", "routing_findings")


def test_successful_run_is_logged_too(runner, tmp_path, monkeypatch):
    _git_init(tmp_path)
    binary = tmp_path / "claude"
    payload = {"zusammenfassung": "ok", "fehler": [], "loesungen": [], "verbesserungen": [], "prompts": [],
               **{name: dict(_B516_VALID_FINDING) for name in _B516_FINDING_NAMES}}
    binary.write_text('#!/bin/sh\n[ "$1" = "--version" ] && { echo "2.1.206"; exit 0; }\n' + "cat <<'J'\n" + json.dumps({"is_error": False, "result": json.dumps(payload)}) + "\nJ\n", encoding="utf-8"); binary.chmod(0o755)
    (tmp_path / "docs").mkdir(); (tmp_path / "docs" / "p.md").write_text("Auftrag"); (tmp_path / "tools").mkdir(); (tmp_path / "tools" / "s.json").write_text(json.dumps({"permissions": {"deny": ["Read(**/.env*)"]}}))
    monkeypatch.setattr(runner, "load_mode", lambda repo_dir: ("local", "")); monkeypatch.setattr(runner, "load_config", lambda repo_dir: _config(binary))
    assert runner.main(["--repo-dir", str(tmp_path), "--force"]) == 0; assert (tmp_path / "run.log").is_file()


def test_log_path_is_configurable():
    import config
    assert "log_path" in config.LOCAL_ANALYSIS_CONFIG; assert config.LOCAL_ANALYSIS_CONFIG["log_path"].startswith("train_data/evaluation/")
