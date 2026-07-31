"""P103: Wiederholte Plateaus (Gleichstand, B490) loesten bisher keine Reaktion aus.
Diese Tests verankern die Eskalation nach 3 Plateaus in Folge und den 14-Tage-Stall-Alarm."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tools.tuning_apply as ta  # noqa: E402


def _wire(tmp_path, monkeypatch):
    eval_dir = tmp_path / "train_data" / "evaluation"
    eval_dir.mkdir(parents=True)
    monkeypatch.setattr(ta, "_enabled", lambda: True)
    monkeypatch.setattr(ta, "STATE_FILE", eval_dir / "tuning_state.json")
    monkeypatch.setattr(ta, "HISTORY_FILE", eval_dir / "tuning_history.jsonl")
    monkeypatch.setattr(ta, "DRIFT_FILE", eval_dir / "drift_status.json")
    monkeypatch.setattr(ta.runtime_config, "patch", lambda d: d)
    return eval_dir


def _plateau_state(eval_dir):
    (eval_dir / "tuning_state.json").write_text(json.dumps({
        "baselines": {"KINEMATIC_EWMA_ALPHA": 0.6},
        "pending": {"KINEMATIC_EWMA_ALPHA": {"new": 0.5, "old": 0.6, "reason": "t"}},
        "mae_before": {"10": 3.0},
        "plateau_streak": json.loads((eval_dir / "tuning_state.json").read_text()).get("plateau_streak", 0)
                          if (eval_dir / "tuning_state.json").exists() else 0,
    }))
    (eval_dir / "drift_status.json").write_text(json.dumps(
        {"quality_target_by_horizon": {"10": {"actual_mae_km": 3.0}}}))


def test_three_plateaus_trigger_escalation(tmp_path, monkeypatch):
    eval_dir = _wire(tmp_path, monkeypatch)
    for _ in range(3):
        _plateau_state(eval_dir)
        ta.cmd_verify()
    state = json.loads((eval_dir / "tuning_state.json").read_text())
    assert state.get("plateau_streak") == 3
    assert state.get("escalation_needed") is True
    lines = [json.loads(l) for l in (eval_dir / "tuning_history.jsonl").read_text().splitlines()]
    assert any(e.get("action") == "escalation_triggered" for e in lines)


def test_apply_is_paused_while_escalation_needed(tmp_path, monkeypatch):
    eval_dir = _wire(tmp_path, monkeypatch)
    (eval_dir / "tuning_state.json").write_text(json.dumps({"escalation_needed": True}))
    (eval_dir / "local_analysis_status.json").write_text(json.dumps(
        {"state": "ok", "last_success_date": "2026-07-31"}))
    (eval_dir / "analysis_result.json").write_text(json.dumps(
        {"tuning_proposals": {"KINEMATIC_EWMA_ALPHA": {"value": 0.5, "reason": "t"}}}))
    monkeypatch.setattr(ta, "STATUS_FILE", eval_dir / "local_analysis_status.json")
    monkeypatch.setattr(ta, "RESULT_FILE", eval_dir / "analysis_result.json")
    patched = {}
    monkeypatch.setattr(ta.runtime_config, "patch", lambda d: patched.update(d) or d)
    assert ta.cmd_apply() == 0
    assert patched == {}


def test_real_improvement_resets_plateau_streak(tmp_path, monkeypatch):
    eval_dir = _wire(tmp_path, monkeypatch)
    (eval_dir / "tuning_state.json").write_text(json.dumps({
        "baselines": {"KINEMATIC_EWMA_ALPHA": 0.6},
        "pending": {"KINEMATIC_EWMA_ALPHA": {"new": 0.5, "old": 0.6, "reason": "t"}},
        "mae_before": {"10": 3.0},
        "plateau_streak": 2, "escalation_needed": False,
    }))
    (eval_dir / "drift_status.json").write_text(json.dumps(
        {"quality_target_by_horizon": {"10": {"actual_mae_km": 2.0}}}))
    ta.cmd_verify()
    state = json.loads((eval_dir / "tuning_state.json").read_text())
    assert state["plateau_streak"] == 0
    assert "escalation_needed" not in state


def test_stall_alarm_after_14_days_without_acceptance(tmp_path, monkeypatch):
    eval_dir = _wire(tmp_path, monkeypatch)
    old_ts = (datetime.now(timezone.utc) - timedelta(days=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (eval_dir / "tuning_history.jsonl").write_text(
        json.dumps({"ts": old_ts, "action": "rejected", "param": "x"}) + "\n")
    state = {}
    stalled = ta._check_stall(state)
    assert stalled is True
    assert state.get("quality_improvement_stalled") is True


def test_no_stall_alarm_with_recent_acceptance(tmp_path, monkeypatch):
    eval_dir = _wire(tmp_path, monkeypatch)
    recent_ts = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (eval_dir / "tuning_history.jsonl").write_text(
        json.dumps({"ts": recent_ts, "action": "accepted", "param": "x"}) + "\n")
    state = {}
    stalled = ta._check_stall(state)
    assert stalled is False
    assert "quality_improvement_stalled" not in state
