"""P92 — Deterministischer Check AC-007 (Eindeutigkeit der Lineage-Ereignisse).
Schema (event_signature/event_type, write_status.last_result) aus cell_lineage.py belegt.
"""
import json
from pathlib import Path

from tools.ai_checks import parse_open_acs, run_all
from tools.ai_checks.checks_local import check_ac007_lineage_event_uniqueness as ac007

REPO = Path(__file__).resolve().parents[1]
AICHECKS = REPO / "AIChecks.md"


def _write(tmp_path, events=None, last_result=None):
    if events is not None:
        d = tmp_path / "train_data" / "cell_lineage"
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "cell_lineage_events.jsonl", "w", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")
    if last_result is not None:
        s = tmp_path / "train_data" / "system"
        s.mkdir(parents=True, exist_ok=True)
        (s / "cell_lineage_write_status.json").write_text(
            json.dumps({"last_result": last_result}), encoding="utf-8")
    return tmp_path


def _merge(sig):
    return {"event_type": "cell_merge", "event_signature": sig}


def _split(sig):
    return {"event_type": "cell_split", "event_signature": sig}


def test_ok_unique_with_merge(tmp_path):
    _write(tmp_path, events=[_merge("m1"), _split("s1")], last_result="ok")
    assert ac007(tmp_path)["status"] == "ok"


def test_finding_duplicate_signature(tmp_path):
    _write(tmp_path, events=[_merge("m1"), _merge("m1")])
    r = ac007(tmp_path)
    assert r["status"] == "finding" and "event_signature" in r["beleg"]


def test_finding_no_merge_event(tmp_path):
    _write(tmp_path, events=[_split("s1"), _split("s2")])
    r = ac007(tmp_path)
    assert r["status"] == "finding" and "cell_merge" in r["beleg"]


def test_finding_write_status_error(tmp_path):
    _write(tmp_path, events=[_merge("m1")], last_result="error")
    assert ac007(tmp_path)["status"] == "finding"


def test_events_without_signature_skipped(tmp_path):
    _write(tmp_path, events=[{"event_type": "cell_merge"}, {"event_type": "cell_merge"}])
    assert ac007(tmp_path)["status"] == "ok"


def test_ok_missing_files(tmp_path):
    assert ac007(tmp_path)["status"] == "ok"


def test_harness_now_implements_ac007():
    summary = run_all(REPO, AICHECKS)
    by = {r["ac"]: r for r in summary["results"]}
    assert by["AC-007"]["status"] != "not_implemented"
    assert summary["total_acs"] == len(parse_open_acs(AICHECKS))
