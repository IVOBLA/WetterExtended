from pathlib import Path

from tools.run_local_analysis import FINDING_CONTRACT


PROMPT = Path("docs/LOCAL_ANALYSIS_PROMPT.md")


def test_missing_b510_finding_field_names_are_documented() -> None:
    prompt = PROMPT.read_text(encoding="utf-8")

    assert "`next_falsifiable_action`" in prompt
    assert "`eligible_for_autonomous_experiment`" in prompt


def test_all_finding_contract_names_are_documented_in_backticks() -> None:
    prompt = PROMPT.read_text(encoding="utf-8")

    missing = [field for field in FINDING_CONTRACT if f"`{field}`" not in prompt]

    assert missing == []
