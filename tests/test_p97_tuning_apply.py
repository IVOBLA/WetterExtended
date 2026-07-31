"""P97 — Autonomes Tuning: Apply/Verify/Rollback-Modul."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.tuning_apply import validate_proposal, cmd_apply, cmd_verify  # noqa: E402
import tools.tuning_apply as ta  # noqa: E402


def test_valid_proposal():
    assert validate_proposal("KINEMATIC_EWMA_ALPHA", 0.5) is None

def test_reject_unknown_param():
    assert validate_proposal("BOGUS_PARAM", 1.0) is not None

def test_reject_out_of_bounds():
    assert validate_proposal("KINEMATIC_EWMA_ALPHA", 0.1) is not None

def test_reject_wrong_step():
    assert validate_proposal("KINEMATIC_EWMA_ALPHA", 0.37) is not None

def test_apply_skips_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(ta, "_enabled", lambda: False)
    assert cmd_apply() == 0

def test_apply_applies_valid_proposal(tmp_path, monkeypatch):
    eval_dir = tmp_path / "train_data" / "evaluation"
    eval_dir.mkdir(parents=True)
    (eval_dir / "analysis_result.json").write_text(json.dumps({
        "tuning_proposals": {"KINEMATIC_EWMA_ALPHA": {"value": 0.5, "reason": "test"}}
    }))
    (eval_dir / "local_analysis_status.json").write_text(json.dumps({
        "state": "ok", "last_success_date": "2026-07-31"
    }))
    (eval_dir / "drift_status.json").write_text(json.dumps({
        "quality_target_by_horizon": {"10": {"actual_mae_km": 3.0}}
    }))
    monkeypatch.setattr(ta, "_enabled", lambda: True)
    monkeypatch.setattr(ta, "EVAL_DIR", eval_dir)
    monkeypatch.setattr(ta, "STATE_FILE", eval_dir / "tuning_state.json")
    monkeypatch.setattr(ta, "HISTORY_FILE", eval_dir / "tuning_history.jsonl")
    monkeypatch.setattr(ta, "RESULT_FILE", eval_dir / "analysis_result.json")
    monkeypatch.setattr(ta, "DRIFT_FILE", eval_dir / "drift_status.json")
    monkeypatch.setattr(ta, "STATUS_FILE", eval_dir / "local_analysis_status.json")
    patched = {}
    monkeypatch.setattr(ta.runtime_config, "patch", lambda d: patched.update(d) or d)
    monkeypatch.setattr(ta.runtime_config, "get", lambda k, d=None: d)
    assert cmd_apply() == 0
    assert patched.get("KINEMATIC_EWMA_ALPHA") == 0.5

def test_verify_accepts_on_improvement(tmp_path, monkeypatch):
    eval_dir = tmp_path / "train_data" / "evaluation"
    eval_dir.mkdir(parents=True)
    (eval_dir / "tuning_state.json").write_text(json.dumps({
        "baselines": {"KINEMATIC_EWMA_ALPHA": 0.6},
        "pending": {"KINEMATIC_EWMA_ALPHA": {"new": 0.5, "old": 0.6, "reason": "test"}},
        "mae_before": {"10": 3.0},
    }))
    (eval_dir / "drift_status.json").write_text(json.dumps({
        "quality_target_by_horizon": {"10": {"actual_mae_km": 2.5}}
    }))
    monkeypatch.setattr(ta, "_enabled", lambda: True)
    monkeypatch.setattr(ta, "STATE_FILE", eval_dir / "tuning_state.json")
    monkeypatch.setattr(ta, "HISTORY_FILE", eval_dir / "tuning_history.jsonl")
    monkeypatch.setattr(ta, "DRIFT_FILE", eval_dir / "drift_status.json")
    monkeypatch.setattr(ta.runtime_config, "patch", lambda d: d)
    assert cmd_verify() == 0
    st = json.loads((eval_dir / "tuning_state.json").read_text())
    assert st["pending"] == {}
    assert st["baselines"]["KINEMATIC_EWMA_ALPHA"] == 0.5

def test_verify_rollbacks_on_degradation(tmp_path, monkeypatch):
    eval_dir = tmp_path / "train_data" / "evaluation"
    eval_dir.mkdir(parents=True)
    (eval_dir / "tuning_state.json").write_text(json.dumps({
        "baselines": {"KINEMATIC_EWMA_ALPHA": 0.6},
        "pending": {"KINEMATIC_EWMA_ALPHA": {"new": 0.5, "old": 0.6, "reason": "test"}},
        "mae_before": {"10": 3.0},
    }))
    (eval_dir / "drift_status.json").write_text(json.dumps({
        "quality_target_by_horizon": {"10": {"actual_mae_km": 4.0}}
    }))
    rolled = {}
    monkeypatch.setattr(ta, "_enabled", lambda: True)
    monkeypatch.setattr(ta, "STATE_FILE", eval_dir / "tuning_state.json")
    monkeypatch.setattr(ta, "HISTORY_FILE", eval_dir / "tuning_history.jsonl")
    monkeypatch.setattr(ta, "DRIFT_FILE", eval_dir / "drift_status.json")
    monkeypatch.setattr(ta.runtime_config, "patch", lambda d: rolled.update(d) or d)
    assert cmd_verify() == 0
    assert rolled.get("KINEMATIC_EWMA_ALPHA") == 0.6
