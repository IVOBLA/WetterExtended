"""P79: Der Report-Mailjob waehlt die Quelle anhand der Betriebsart."""
from __future__ import annotations

import ast
import json
import os
import time
import types
from pathlib import Path

import pytest


def _load_report_job(tmp_path, logs, overrides=None):
    source = Path("scheduler.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    func = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run_claude_code_report_job")
    rc = types.SimpleNamespace(
        reload_overrides=lambda: None,
        get=lambda name, default=None: (overrides or {}).get(name, {} if default is None else default),
    )
    ns = {"runtime_config": rc, "debug_log": lambda m: logs.append(str(m)), "__file__": str(tmp_path / "scheduler.py"), "__name__": "scheduler_p79"}
    exec(compile(ast.Module(body=[func], type_ignores=[]), "scheduler.py", "exec"), ns)
    return ns["run_claude_code_report_job"]


@pytest.fixture
def env(monkeypatch, tmp_path):
    import config
    import email_notifier
    import subprocess

    logs, sent, git_calls = [], [], []
    state = {"overrides": {}}

    def _send(result, email):
        sent.append((result, email))
        return True

    monkeypatch.setattr(email_notifier, "send_claude_code_report_email", _send)

    def _no_git(cmd, **kwargs):
        git_calls.append(list(cmd))
        raise AssertionError("git darf in Betriebsart 'local' nicht laufen")

    def set_cfg(**over):
        cc = dict(config.CLAUDE_CODE_REPORT_CONFIG)
        cc.update(over)
        monkeypatch.setattr(config, "CLAUDE_CODE_REPORT_CONFIG", cc, raising=False)

    def set_mode(mode):
        state["overrides"]["ANALYSIS_MODE"] = mode

    def set_result(payload, age_h=0.0, raw=None):
        target = tmp_path / "train_data" / "evaluation" / "analysis_result.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(raw if raw is not None else json.dumps(payload), encoding="utf-8")
        if age_h:
            old = time.time() - age_h * 3600
            os.utime(target, (old, old))
        return target

    def run():
        _load_report_job(tmp_path, logs, state["overrides"])()

    return types.SimpleNamespace(logs=logs, sent=sent, git_calls=git_calls, tmp=tmp_path, set_cfg=set_cfg, set_mode=set_mode, set_result=set_result, no_git=_no_git, subprocess=subprocess, monkeypatch=monkeypatch, run=run)


def test_local_mode_sends_local_file_without_git(env):
    env.set_cfg(enabled=True, report_email="a@b.c")
    env.set_mode("local")
    env.set_result({"zusammenfassung": "lokal", "fehler": []})
    env.monkeypatch.setattr(env.subprocess, "run", env.no_git)
    env.run()
    assert env.sent
    assert env.sent[0][0]["zusammenfassung"] == "lokal"
    assert env.git_calls == []
    assert any("Betriebsart: local" in m for m in env.logs)


def test_local_mode_skips_when_file_missing(env):
    env.set_cfg(enabled=True, report_email="a@b.c"); env.set_mode("local")
    env.monkeypatch.setattr(env.subprocess, "run", env.no_git); env.run()
    assert env.sent == []
    assert any("lokale Datei fehlt" in m for m in env.logs)


def test_local_mode_skips_stale_file(env):
    env.set_cfg(enabled=True, report_email="a@b.c"); env.set_mode("local")
    env.set_result({"zusammenfassung": "alt"}, age_h=48.0)
    env.monkeypatch.setattr(env.subprocess, "run", env.no_git); env.run()
    assert env.sent == []
    assert any(">26h" in m for m in env.logs)


def test_local_mode_accepts_file_just_under_the_limit(env):
    env.set_cfg(enabled=True, report_email="a@b.c"); env.set_mode("local")
    env.set_result({"zusammenfassung": "frisch genug"}, age_h=25.0)
    env.monkeypatch.setattr(env.subprocess, "run", env.no_git); env.run()
    assert env.sent


def test_local_mode_skips_broken_json(env):
    env.set_cfg(enabled=True, report_email="a@b.c"); env.set_mode("local")
    env.set_result(None, raw="{kaputt")
    env.monkeypatch.setattr(env.subprocess, "run", env.no_git); env.run()
    assert env.sent == []
    assert any("nicht lesbar" in m for m in env.logs)


def test_unknown_mode_sends_nothing(env):
    env.set_cfg(enabled=True, report_email="a@b.c"); env.set_mode("quatsch")
    env.monkeypatch.setattr(env.subprocess, "run", env.no_git); env.run()
    assert env.sent == []
    assert any("unbekannte Betriebsart" in m for m in env.logs)


def test_disabled_still_wins_over_mode(env):
    env.set_cfg(enabled=False, report_email="a@b.c"); env.set_mode("local")
    env.set_result({"zusammenfassung": "x"}); env.monkeypatch.setattr(env.subprocess, "run", env.no_git); env.run()
    assert env.sent == []


def test_empty_email_still_wins_over_mode(env):
    env.set_cfg(enabled=True, report_email="   "); env.set_mode("local")
    env.set_result({"zusammenfassung": "x"}); env.monkeypatch.setattr(env.subprocess, "run", env.no_git); env.run()
    assert env.sent == []


def test_repo_is_the_default():
    import config
    assert config.ANALYSIS_MODE == "repo"


def test_repo_mode_still_uses_git(env):
    from datetime import datetime, timezone
    calls = []
    class _R:
        def __init__(self, out="", rc=0):
            self.stdout, self.stderr, self.returncode = out, "", rc
    def _fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        if list(cmd[:2]) == ["git", "fetch"]: return _R()
        if list(cmd[:2]) == ["git", "log"]: return _R(datetime.now(timezone.utc).isoformat())
        if list(cmd[:2]) == ["git", "show"]: return _R(json.dumps({"zusammenfassung": "vom branch"}))
        return _R(rc=1)
    env.set_cfg(enabled=True, report_email="a@b.c")
    env.monkeypatch.setattr(env.subprocess, "run", _fake_run); env.run()
    assert any(list(c[:2]) == ["git", "show"] for c in calls)
    assert env.sent[0][0]["zusammenfassung"] == "vom branch"


def test_startup_log_names_the_active_mode():
    src = Path("scheduler.py").read_text(encoding="utf-8")
    assert "Betriebsart: {_cc_mode}" in src
