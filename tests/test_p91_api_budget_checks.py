"""P91 — Deterministische Budget-Checks AC-048 (Gruppen-Normalisierung) und
AC-049 (Provider-Summe > 70 %). Nutzt das echte group_for() + config.API_DAILY_BUDGET.
"""
import json
from pathlib import Path

import config
from tools.ai_checks import parse_open_acs, run_all
from tools.ai_checks.checks_local import (
    check_ac048_budget_group_normalization as ac048,
    check_ac049_provider_budget_usage as ac049,
)

REPO = Path(__file__).resolve().parents[1]
AICHECKS = REPO / "AIChecks.md"
_LIMIT = int(config.API_DAILY_BUDGET["openmeteo"])


def _write_budget(tmp_path, counts):
    d = tmp_path / "train_data" / "evaluation"
    d.mkdir(parents=True, exist_ok=True)
    (d / "api_budget.json").write_text(json.dumps({"date": "2026-07-29", "counts": counts}),
                                       encoding="utf-8")
    return tmp_path


def test_ac048_finding_on_collision(tmp_path):
    _write_budget(tmp_path, {"openmeteo": 100, "open-meteo-forecast": 5})
    r = ac048(tmp_path)
    assert r["status"] == "finding" and "openmeteo" in r["beleg"]


def test_ac048_ok_without_collision(tmp_path):
    _write_budget(tmp_path, {"openmeteo": 100, "geosphere": 5})
    assert ac048(tmp_path)["status"] == "ok"


def test_ac048_ok_missing_file(tmp_path):
    assert ac048(tmp_path)["status"] == "ok"


def test_ac049_finding_over_70pct(tmp_path):
    _write_budget(tmp_path, {"openmeteo": int(_LIMIT * 0.8)})
    r = ac049(tmp_path)
    assert r["status"] == "finding" and "openmeteo" in r["beleg"]


def test_ac049_ok_under_70pct(tmp_path):
    _write_budget(tmp_path, {"openmeteo": int(_LIMIT * 0.1)})
    assert ac049(tmp_path)["status"] == "ok"


def test_ac049_ok_missing_file(tmp_path):
    assert ac049(tmp_path)["status"] == "ok"


def test_harness_now_implements_048_049():
    summary = run_all(REPO, AICHECKS)
    by = {r["ac"]: r for r in summary["results"]}
    assert by["AC-048"]["status"] != "not_implemented"
    assert by["AC-049"]["status"] != "not_implemented"
    assert summary["total_acs"] == len(parse_open_acs(AICHECKS))
