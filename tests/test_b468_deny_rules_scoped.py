"""B468: Deny-Regeln muessen qualifiziert sein — sonst bricht der ganze Lauf ab.

Befund im Betrieb (2026-07-24 11:48, Zustand "failed" nach 470 s):

    Permission deny rule "MultiEdit" matches no known tool — check for typos.

Ein blosser Werkzeugname in permissions.deny laesst die CLI abbrechen, sobald das
Werkzeug in der installierten Version nicht existiert. MultiEdit gibt es in 2.1.206
nicht mehr. Unter --permission-mode dontAsk sind nicht vorab erlaubte Werkzeuge
ohnehin gesperrt; blosse Namen waren also reine Bruchstelle ohne Schutzgewinn.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SETTINGS = REPO / "tools" / "local_analysis_settings.json"
TOOL = REPO / "tools" / "run_local_analysis.py"


@pytest.fixture
def runner(monkeypatch):
    spec = importlib.util.spec_from_file_location("run_local_analysis_b468", TOOL)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def _deny():
    return json.loads(SETTINGS.read_text(encoding="utf-8"))["permissions"]["deny"]


# --------------------------------------------------------------------------
# Die ausgelieferte Datei
# --------------------------------------------------------------------------

def test_no_bare_tool_names_remain():
    bare = [r for r in _deny() if "(" not in r]
    assert bare == [], f"Blosse Werkzeugnamen brechen den Lauf ab: {bare}"


def test_multiedit_is_gone():
    """Der konkrete Ausloeser des Betriebsfehlers."""
    assert not any("MultiEdit" in r for r in _deny())


def test_every_rule_is_closed():
    for rule in _deny():
        assert rule.endswith(")"), f"Unvollstaendige Regel: {rule}"


def test_load_bearing_rules_survived():
    """Read ist breit erlaubt — die Pfadsperren sind die einzigen wirksamen Regeln."""
    deny = _deny()
    for needed in ("Read(./.env)", "Read(./.env.*)", "Read(**/.env)"):
        assert needed in deny, f"Schutzregel verloren: {needed}"


def test_shell_rules_survived():
    deny = _deny()
    for needed in ("Bash(rm *)", "Bash(sudo *)", "Bash(git push *)"):
        assert needed in deny


def test_only_allowlisted_tools_are_denied(runner):
    """Eine Regel fuer ein nicht erlaubtes Werkzeug ist wirkungslos."""
    erlaubt = set(runner.ALLOWED_PLAIN_TOOLS) | {
        r.split("(", 1)[0] for r in runner.ALLOWED_BASH_RULES
    }
    for rule in _deny():
        assert rule.split("(", 1)[0] in erlaubt, f"Wirkungslose Regel: {rule}"


# --------------------------------------------------------------------------
# Der Guard im Runner
# --------------------------------------------------------------------------

def test_shipped_settings_pass_the_guard(runner):
    runner.validate_deny_rules(
        json.loads(SETTINGS.read_text(encoding="utf-8")), SETTINGS
    )


@pytest.mark.parametrize("rule", [
    "MultiEdit", "Write", "Edit", "WebFetch", "WebSearch", "NotebookEdit",
])
def test_bare_names_are_rejected(runner, rule):
    with pytest.raises(runner.PreconditionError) as exc:
        runner.validate_deny_rules({"permissions": {"deny": [rule]}}, "x.json")
    assert "ohne Muster" in str(exc.value)


def test_rules_for_unallowed_tools_are_rejected(runner):
    with pytest.raises(runner.PreconditionError) as exc:
        runner.validate_deny_rules(
            {"permissions": {"deny": ["Write(./x)"]}}, "x.json")
    assert "nicht erlaubtes Werkzeug" in str(exc.value)


def test_unclosed_rule_is_rejected(runner):
    with pytest.raises(runner.PreconditionError):
        runner.validate_deny_rules({"permissions": {"deny": ["Bash(rm *"]}}, "x.json")


def test_missing_deny_section_is_tolerated(runner):
    runner.validate_deny_rules({}, "x.json")
    runner.validate_deny_rules({"permissions": {}}, "x.json")


def test_non_list_deny_is_rejected(runner):
    with pytest.raises(runner.PreconditionError):
        runner.validate_deny_rules({"permissions": {"deny": "Write"}}, "x.json")


def test_guard_runs_as_a_precondition(runner, tmp_path, monkeypatch):
    """Der Lauf muss VOR dem CLI-Aufruf scheitern, nicht erst nach 470 Sekunden."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "p.md").write_text("Auftrag", encoding="utf-8")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "s.json").write_text(
        json.dumps({"permissions": {"deny": ["MultiEdit"]}}), encoding="utf-8")
    monkeypatch.setattr(runner, "resolve_claude_bin", lambda cfg: "/usr/bin/claude")
    monkeypatch.setattr(runner, "load_mode", lambda repo_dir: ("local", ""))
    monkeypatch.setattr(runner, "load_config", lambda repo_dir: {
        "cron_hour": 0, "cron_minute": 0,
        "allowed_tools": "Read,Grep,Glob,Bash(python3 tools/ro_query.py *)",
        "prompt_path": "docs/p.md", "settings_path": "tools/s.json",
        "status_path": "status.json", "result_path": "result.json",
    })

    def _never(*a, **k):
        raise AssertionError("Die CLI darf bei ungueltigen Deny-Regeln nicht starten")

    monkeypatch.setattr(runner.subprocess, "run", _never)

    assert runner.main(["--repo-dir", str(tmp_path), "--force"]) == 1
    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert status["state"] == "precondition_failed"
    assert "MultiEdit" in status["error"]
