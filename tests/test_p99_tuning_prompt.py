"""P99 — Analyse-Prompt-Erweiterung: tuning_proposals."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROMPT = REPO / "docs" / "LOCAL_ANALYSIS_PROMPT.md"
RUNNER = REPO / "tools" / "run_local_analysis.py"

def _prompt(): return PROMPT.read_text(encoding="utf-8")

def test_section_t_exists():
    assert "## T. Autonomes Parameter-Tuning" in _prompt()

def test_tuning_proposals_in_output_format():
    assert "tuning_proposals" in _prompt()

def test_max_one_experiment_rule():
    assert "höchstens einem Standardexperiment" in _prompt()

def test_requires_code_ref_in_reason():
    assert "code_ref" in _prompt().split("## T.")[1].split("## B.")[0]

def test_runner_accepts_tuning_proposals():
    assert "tuning_proposals" in RUNNER.read_text(encoding="utf-8")

def test_only_when_enabled_rule():
    section_t = _prompt().split("## T.")[1].split("## B.")[0]
    assert "AUTONOMOUS_TUNING_ENABLED" in section_t
