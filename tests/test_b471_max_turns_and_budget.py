"""B471 — Turn-Limit erhoeht, Abbruch am Limit ist lesbar, Prompt priorisiert Abschnitt A."""
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
RUNNER = REPO / "tools" / "run_local_analysis.py"
PROMPT = REPO / "docs" / "LOCAL_ANALYSIS_PROMPT.md"


@pytest.fixture
def rla():
    spec = importlib.util.spec_from_file_location("rla_b471", RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_detect_incomplete_on_max_turns(rla):
    out = json.dumps({"terminal_reason": "max_turns",
                      "errors": ["Reached maximum number of turns (40)"]})
    assert rla.detect_incomplete(out)


def test_detect_incomplete_via_error_text(rla):
    out = json.dumps({"errors": ["Reached maximum number of turns (70)"]})
    assert rla.detect_incomplete(out)


def test_detect_incomplete_none_on_normal_error(rla):
    assert rla.detect_incomplete(json.dumps({"is_error": True, "result": "x"})) is None


def test_detect_incomplete_none_on_garbage(rla):
    assert rla.detect_incomplete("kein json") is None


def test_config_budget_raised():
    import config
    cfg = config.LOCAL_ANALYSIS_CONFIG
    assert cfg["max_turns"] >= 70
    assert cfg["timeout_s"] >= 1500


def test_prompt_puts_fixed_checks_first():
    text = PROMPT.read_text(encoding="utf-8")
    a = text.index("## A. Feste Betriebsprüfungen")
    b = text.index("## B. Offene Arbeitsanweisungen")
    assert a < b, "Feste Prüfungen (A) müssen vor den offenen ACs (B) stehen"


def test_prompt_has_step_budget_and_shell_ban():
    text = PROMPT.read_text(encoding="utf-8")
    assert "Schrittbudget" in text
    assert "SOFORT STOPPEN" in text
    assert "systemctl" in text and "gesperrt" in text
