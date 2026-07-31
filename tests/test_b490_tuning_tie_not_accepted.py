"""B490: Ein exakter Gleichstand (delta_km == 0) durfte bisher wie eine echte
Verbesserung in die Baseline uebernommen werden. Diese Tests verankern, dass nur
delta_km < 0 promotet wird; Gleichstand und Verschlechterung werden beide
zurueckgerollt, aber mit unterscheidbarem Grund."""
import json
import sys
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
    return eval_dir


def test_exact_tie_is_rolled_back_not_accepted(tmp_path, monkeypatch):
    eval_dir = _wire(tmp_path, monkeypatch)
    (eval_dir / "tuning_state.json").write_text(json.dumps({
        "baselines": {"KINEMATIC_EWMA_ALPHA": 0.6},
        "pending": {"KINEMATIC_EWMA_ALPHA": {"new": 0.5, "old": 0.6, "reason": "test"}},
        "mae_before": {"10": 3.0},
    }))
    (eval_dir / "drift_status.json").write_text(json.dumps(
        {"quality_target_by_horizon": {"10": {"actual_mae_km": 3.0}}}))
    rolled = {}
    monkeypatch.setattr(ta.runtime_config, "patch", lambda d: rolled.update(d) or d)
    assert ta.cmd_verify() == 0
    assert rolled.get("KINEMATIC_EWMA_ALPHA") == 0.6
    st = json.loads((eval_dir / "tuning_state.json").read_text())
    assert st["baselines"]["KINEMATIC_EWMA_ALPHA"] == 0.6, "Baseline darf bei Gleichstand nicht wechseln"


def test_tie_and_degradation_have_distinct_history_reasons(tmp_path, monkeypatch):
    eval_dir = _wire(tmp_path, monkeypatch)
    (eval_dir / "tuning_state.json").write_text(json.dumps({
        "baselines": {"KINEMATIC_EWMA_ALPHA": 0.6},
        "pending": {"KINEMATIC_EWMA_ALPHA": {"new": 0.5, "old": 0.6, "reason": "test"}},
        "mae_before": {"10": 3.0},
    }))
    (eval_dir / "drift_status.json").write_text(json.dumps(
        {"quality_target_by_horizon": {"10": {"actual_mae_km": 3.0}}}))
    monkeypatch.setattr(ta.runtime_config, "patch", lambda d: d)
    ta.cmd_verify()
    lines = (eval_dir / "tuning_history.jsonl").read_text().splitlines()
    entry = json.loads(lines[-1])
    assert entry["reason"] == "plateau_no_measurable_improvement"


def test_real_improvement_is_still_accepted(tmp_path, monkeypatch):
    eval_dir = _wire(tmp_path, monkeypatch)
    (eval_dir / "tuning_state.json").write_text(json.dumps({
        "baselines": {"KINEMATIC_EWMA_ALPHA": 0.6},
        "pending": {"KINEMATIC_EWMA_ALPHA": {"new": 0.5, "old": 0.6, "reason": "test"}},
        "mae_before": {"10": 3.0},
    }))
    (eval_dir / "drift_status.json").write_text(json.dumps(
        {"quality_target_by_horizon": {"10": {"actual_mae_km": 2.5}}}))
    monkeypatch.setattr(ta.runtime_config, "patch", lambda d: d)
    assert ta.cmd_verify() == 0
    st = json.loads((eval_dir / "tuning_state.json").read_text())
    assert st["baselines"]["KINEMATIC_EWMA_ALPHA"] == 0.5
