"""P83 — Regression: deterministischer AIChecks-Harness.

Garantiert, dass JEDER offene AC bei jedem Lauf ein Ergebnis erhaelt (Vollstaendigkeit,
unabhaengig vom LLM-Budget) und dass ein werfender Check den Gesamtlauf nicht abbricht.
"""
import json
from pathlib import Path

from tools.ai_checks import parse_open_acs, run_all
from tools.ai_checks.runner import main as runner_main

REPO = Path(__file__).resolve().parents[1]
AICHECKS = REPO / "AIChecks.md"


def test_parse_open_acs_nonempty_and_only_open():
    ids = [a for a, _ in parse_open_acs(AICHECKS)]
    assert ids, "keine ACs im Abschnitt '## Offen' gefunden"
    assert "AC-080" in ids
    assert len(ids) == len(set(ids)), "doppelte AC-Ids"


def test_run_all_covers_every_open_ac():
    acs = parse_open_acs(AICHECKS)
    summary = run_all(REPO, AICHECKS)
    assert summary["total_acs"] == len(acs)
    assert {r["ac"] for r in summary["results"]} == {a for a, _ in acs}
    for r in summary["results"]:
        assert r["status"] in {"ok", "finding", "error", "not_implemented"}


def test_ac080_is_implemented():
    summary = run_all(REPO, AICHECKS)
    r = next(x for x in summary["results"] if x["ac"] == "AC-080")
    assert r["status"] != "not_implemented"


def test_ac080_flags_incomplete(tmp_path):
    ev = tmp_path / "train_data" / "evaluation"
    ev.mkdir(parents=True)
    (ev / "local_analysis_status.json").write_text(
        json.dumps({"state": "incomplete", "error": "Schritt-Limit erreicht"}),
        encoding="utf-8")
    from tools.ai_checks.checks_local import check_ac080_incomplete_step_budget as chk
    r = chk(tmp_path)
    assert r["status"] == "finding"
    assert "incomplete" in r["beleg"]


def test_ac080_ok_when_state_ok(tmp_path):
    ev = tmp_path / "train_data" / "evaluation"
    ev.mkdir(parents=True)
    (ev / "local_analysis_status.json").write_text(
        json.dumps({"state": "ok"}), encoding="utf-8")
    from tools.ai_checks.checks_local import check_ac080_incomplete_step_budget as chk
    r = chk(tmp_path)
    assert r["status"] == "ok"


def test_broken_check_does_not_abort_run():
    acs = parse_open_acs(AICHECKS)

    def boom(base):
        raise RuntimeError("kaputt")

    summary = run_all(REPO, AICHECKS, checks={acs[0][0]: boom})
    assert summary["total_acs"] == len(acs)
    r = next(x for x in summary["results"] if x["ac"] == acs[0][0])
    assert r["status"] == "error" and "kaputt" in r["beleg"]


def test_runner_writes_results(tmp_path):
    out = tmp_path / "ai_checks_results.json"
    rc = runner_main(["--base", str(REPO), "--out", str(out)])
    assert rc == 0 and out.is_file()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["total_acs"] == len(parse_open_acs(AICHECKS))
