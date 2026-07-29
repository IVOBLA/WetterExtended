"""P88 — Verdrahtung: run_local_analysis fuehrt den deterministischen AIChecks-Harness
vor der LLM-Analyse aus und schreibt ai_checks_results.json. Ausfallsicher: ein
Harness-Fehler blockiert die LLM-Analyse nicht (Fallback greift).
"""
import json
import shutil
from pathlib import Path

from tools.run_local_analysis import run_deterministic_ai_checks
from tools.ai_checks import parse_open_acs

REPO = Path(__file__).resolve().parents[1]
AICHECKS = REPO / "AIChecks.md"


def test_writes_results_and_returns_summary(tmp_path):
    shutil.copy(AICHECKS, tmp_path / "AIChecks.md")
    summary = run_deterministic_ai_checks(tmp_path)
    assert summary is not None
    out = tmp_path / "train_data" / "evaluation" / "ai_checks_results.json"
    assert out.is_file()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["total_acs"] == len(parse_open_acs(AICHECKS))
    assert {r["ac"] for r in data["results"]} == {a for a, _ in parse_open_acs(AICHECKS)}


def test_graceful_when_aichecks_missing(tmp_path):
    # kein AIChecks.md -> Harness scheitert -> Funktion faengt ab und liefert None,
    # OHNE zu werfen (LLM-Analyse darf nicht blockiert werden).
    result = run_deterministic_ai_checks(tmp_path)
    assert result is None
