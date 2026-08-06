"""B490/B494: Ein exakter Gleichstand (Plateau, mean_delta_km innerhalb der
Mindestmarge) darf nicht wie eine echte Verbesserung promotet werden. Seit dem
Experiment-Umbau entscheidet evaluate_paired_cases() ueber gepaarte Faelle statt
eines einzelnen delta_km-Werts aus drift_status.json."""
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tools.tuning_apply as ta  # noqa: E402


def _apply_experiment(tmp_path, monkeypatch, old=0.6, new=0.55):
    """B494: baut ueber den echten _cmd_apply_unlocked()-Pfad ein gueltiges
    Shadow-Experiment auf. Gibt (eval_dir, experiment_id, manifest, patched,
    runtime_state) zurueck; runtime_state/patched sind gemeinsam gemockt, sodass
    ein spaeterer Verify-Aufruf im selben Test die tatsaechlich "gepatchten"
    Werte ueber runtime_config.get() wiedersieht."""
    experiment_id = str(uuid.uuid4())
    payload = {
        "schema": "wetterextended.local-analysis.v2", "analysis_run_id": str(uuid.uuid4()),
        "source_snapshot_id": "sha256:a", "git_commit": "abc", "result_id": str(uuid.uuid4()),
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tuning_proposals": [{
            "experiment_id": experiment_id, "target_system": "kinematic",
            "target_horizons": [10], "parameter": "KINEMATIC_EWMA_ALPHA",
            "old_value": old, "new_value": new, "code_ref": "prediction.py:_append_kinematic",
            "evidence_refs": ["case:1"], "expected_effect": {"metric": "mae_km", "direction": "decrease", "minimum_change": 0.05},
            "minimum_paired_samples": {"10": 4}, "maximum_runtime_hours": 48,
        }],
    }
    started = datetime.now(timezone.utc) - timedelta(minutes=1)
    status = {k: payload[k] for k in ("analysis_run_id", "source_snapshot_id", "git_commit", "result_id")}
    status.update({"state": "ok", "run_started_at_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ")})
    eval_dir = tmp_path / "train_data" / "evaluation"
    eval_dir.mkdir(parents=True)
    (eval_dir / "analysis_result.json").write_text(json.dumps(payload))
    (eval_dir / "local_analysis_status.json").write_text(json.dumps(status))
    monkeypatch.setattr(ta, "RESULT_FILE", eval_dir / "analysis_result.json")
    monkeypatch.setattr(ta, "STATUS_FILE", eval_dir / "local_analysis_status.json")
    monkeypatch.setattr(ta, "STATE_FILE", eval_dir / "tuning_state.json")
    monkeypatch.setattr(ta, "HISTORY_FILE", eval_dir / "tuning_history.jsonl")
    monkeypatch.setattr(ta, "EXPERIMENTS_DIR", eval_dir / "experiments")
    monkeypatch.setattr(ta, "_enabled", lambda: True)
    monkeypatch.setattr(ta, "_experiments_enabled", lambda: True)
    monkeypatch.setattr(ta.config, "FORECAST_EXPERIMENT_MIN_RUNTIME_HOURS", 0)
    monkeypatch.setattr(ta.config, "FORECAST_EXPERIMENT_MIN_PAIRED_SAMPLES_PER_HORIZON", 4)
    runtime_state = {"KINEMATIC_EWMA_ALPHA": old}
    patched = {}
    monkeypatch.setattr(ta.runtime_config, "get", lambda name, default=None: runtime_state.get(name, default))

    def _patch(values):
        patched.update(values)
        runtime_state.update(values)
        return values
    monkeypatch.setattr(ta.runtime_config, "patch", _patch)
    assert ta.cmd_apply() == 0
    assert patched == {}
    manifest = json.loads((eval_dir / "experiments" / experiment_id / "manifest.json").read_text())
    return eval_dir, experiment_id, manifest, patched, runtime_state


def _write_result(eval_dir, experiment_id, manifest, *, candidate_delta, count=40):
    cases = []
    for i in range(count):
        cases.append({
            "case_key": f"k{i}", "horizon_min": 10, "event_id": f"e{i // 2}", "cell_id": f"c{i // 2}",
            "incumbent_error_km": 2.0, "candidate_error_km": 2.0 + candidate_delta,
            "state": "final", "eligible_for_model_tuning": True, "match_type": "exact_id",
            "experiment_id": experiment_id,
            "policy_hash": manifest["policy_hash"], "verification_config_hash": manifest["verification_config_hash"],
            "matcher_contract_hash": manifest["matcher_contract_hash"],
            "forecast_variant_id_incumbent": manifest["forecast_variant_id_incumbent"],
            "forecast_variant_id_candidate": manifest["forecast_variant_id_candidate"],
            "incumbent_actual_id": "obj1", "candidate_actual_id": "obj1",
            "incumbent_actual_lat": 46.0, "candidate_actual_lat": 46.0,
            "incumbent_actual_lon": 14.0, "candidate_actual_lon": 14.0,
        })
    result = {key: manifest[key] for key in ("experiment_id", "analysis_run_id", "source_snapshot_id",
              "git_commit", "policy_hash", "verification_config_hash", "matcher_contract_hash", "forecast_code_hash")}
    result.update({"schema": ta.EXPERIMENT_SCHEMA, "paired_cases": cases,
                   "eligible_case_count": count, "candidate_missing_count": 0,
                   "candidate_rejected_count": 0, "candidate_fallback_count": 0})
    (eval_dir / "experiments" / experiment_id).mkdir(parents=True, exist_ok=True)
    (eval_dir / "experiments" / experiment_id / "result.json").write_text(json.dumps(result))


def test_exact_tie_is_not_promoted(tmp_path, monkeypatch):
    eval_dir, experiment_id, manifest, patched, _ = _apply_experiment(tmp_path, monkeypatch)
    _write_result(eval_dir, experiment_id, manifest, candidate_delta=0.0)
    assert ta.cmd_verify() == 0
    assert patched == {}, "Gleichstand darf nicht in die Baseline uebernommen werden"
    state = json.loads((eval_dir / "tuning_state.json").read_text())
    assert state.get("baselines", {}).get("KINEMATIC_EWMA_ALPHA") is None


def test_tie_is_recorded_as_plateau_not_accepted(tmp_path, monkeypatch):
    eval_dir, experiment_id, manifest, patched, _ = _apply_experiment(tmp_path, monkeypatch)
    _write_result(eval_dir, experiment_id, manifest, candidate_delta=0.0)
    ta.cmd_verify()
    lines = [json.loads(l) for l in (eval_dir / "tuning_history.jsonl").read_text().splitlines()]
    assert lines[-1]["action"] == "plateau"


def test_real_improvement_is_still_promoted(tmp_path, monkeypatch):
    eval_dir, experiment_id, manifest, patched, _ = _apply_experiment(tmp_path, monkeypatch)
    _write_result(eval_dir, experiment_id, manifest, candidate_delta=-1.0)
    assert ta.cmd_verify() == 0
    assert patched.get("KINEMATIC_EWMA_ALPHA") == 0.55
