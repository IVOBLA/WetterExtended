"""P116 — Deterministische Reifegrad-Pruefung fuer FORECAST_EXPERIMENTS_ENABLED."""
import json
from forecast_experiments_readiness import compute_readiness


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _write_json(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def _criterion(result, name):
    return next(c for c in result["criteria"] if c["id"] == name)


def test_no_data_at_all_is_not_ready(tmp_path):
    r = compute_readiness(tmp_path)
    assert r["overall_ready"] is False
    failing = {c["id"] for c in r["criteria"] if not c["ok"]}
    assert {"gold_match_coverage", "ambiguous_nearest_rate", "completed_experiment_cycle"} <= failing


def test_identical_actuals_guard_is_always_structurally_ok(tmp_path):
    guard = _criterion(compute_readiness(tmp_path), "identical_actuals_guard")
    assert guard["ok"] is True
    assert guard["structural"] is True


def test_all_five_criteria_green(tmp_path):
    _write_jsonl(tmp_path / "accuracy_history.jsonl", [{"samples": 100, "verified": 96, "ambiguous_nearest": 2}, {"samples": 100, "verified": 95, "ambiguous_nearest": 3}])
    _write_jsonl(tmp_path / "tuning_history.jsonl", [{"action": "created"}, {"action": "plateau"}])
    _write_json(tmp_path / "tuning_state.json", {"plateau_streak": 1, "escalation_needed": False})
    r = compute_readiness(tmp_path)
    assert r["overall_ready"] is True
    assert all(c["ok"] for c in r["criteria"])


def test_low_coverage_rate_fails_criterion_1(tmp_path):
    _write_jsonl(tmp_path / "accuracy_history.jsonl", [{"samples": 100, "verified": 60, "ambiguous_nearest": 2}])
    crit = _criterion(compute_readiness(tmp_path), "gold_match_coverage")
    assert crit["ok"] is False
    assert crit["value"] == 0.6


def test_high_coverage_rate_passes_criterion_1(tmp_path):
    _write_jsonl(tmp_path / "accuracy_history.jsonl", [{"samples": 100, "verified": 95, "ambiguous_nearest": 1}])
    assert _criterion(compute_readiness(tmp_path), "gold_match_coverage")["ok"] is True


def test_high_ambiguous_nearest_rate_fails_criterion_2(tmp_path):
    _write_jsonl(tmp_path / "accuracy_history.jsonl", [{"samples": 100, "verified": 95, "ambiguous_nearest": 20}])
    assert _criterion(compute_readiness(tmp_path), "ambiguous_nearest_rate")["ok"] is False


def test_low_ambiguous_nearest_rate_passes_criterion_2(tmp_path):
    _write_jsonl(tmp_path / "accuracy_history.jsonl", [{"samples": 100, "verified": 95, "ambiguous_nearest": 1}])
    assert _criterion(compute_readiness(tmp_path), "ambiguous_nearest_rate")["ok"] is True


def test_no_terminal_tuning_action_fails_criterion_3(tmp_path):
    _write_jsonl(tmp_path / "tuning_history.jsonl", [{"action": "created"}, {"action": "collecting"}])
    assert _criterion(compute_readiness(tmp_path), "completed_experiment_cycle")["ok"] is False


def test_terminal_tuning_action_passes_criterion_3(tmp_path):
    _write_jsonl(tmp_path / "tuning_history.jsonl", [{"action": "created"}, {"action": "improved"}])
    assert _criterion(compute_readiness(tmp_path), "completed_experiment_cycle")["ok"] is True


def test_high_plateau_streak_without_escalation_fails_criterion_4(tmp_path):
    _write_json(tmp_path / "tuning_state.json", {"plateau_streak": 3, "escalation_needed": False})
    assert _criterion(compute_readiness(tmp_path), "escalation_mechanism_consistent")["ok"] is False


def test_high_plateau_streak_with_escalation_passes_criterion_4(tmp_path):
    _write_json(tmp_path / "tuning_state.json", {"plateau_streak": 4, "escalation_needed": True})
    assert _criterion(compute_readiness(tmp_path), "escalation_mechanism_consistent")["ok"] is True


def test_low_plateau_streak_without_escalation_passes_criterion_4(tmp_path):
    _write_json(tmp_path / "tuning_state.json", {"plateau_streak": 1, "escalation_needed": False})
    assert _criterion(compute_readiness(tmp_path), "escalation_mechanism_consistent")["ok"] is True


def test_malformed_jsonl_lines_are_skipped_not_crashed(tmp_path):
    (tmp_path / "accuracy_history.jsonl").write_text('{"samples": 100, "verified": 96, "ambiguous_nearest": 1}\nnicht-json\n', encoding="utf-8")
    assert _criterion(compute_readiness(tmp_path), "gold_match_coverage")["ok"] is True


def test_custom_thresholds_are_respected(tmp_path):
    _write_jsonl(tmp_path / "accuracy_history.jsonl", [{"samples": 100, "verified": 70, "ambiguous_nearest": 1}])
    assert _criterion(compute_readiness(tmp_path, min_coverage_rate=0.5), "gold_match_coverage")["ok"] is True
