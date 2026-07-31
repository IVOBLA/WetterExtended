"""P103/B494: Wiederholte Plateaus loesen eine Eskalation aus (Apply pausiert), und
14 Tage ohne eine echte ('improved') Verbesserung loesen einen Stall-Alarm aus. Seit
dem Experiment-Umbau laeuft ein Plateau ueber evaluate_paired_cases(), nicht mehr
ueber einen einzelnen delta_km-Wert."""
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
            "evidence_refs": ["case:1"], "expected_effect": "MAE sinkt",
            "minimum_paired_samples": {"10": 4}, "maximum_runtime_hours": 48,
        }],
    }
    started = datetime.now(timezone.utc) - timedelta(minutes=1)
    status = {k: payload[k] for k in ("analysis_run_id", "source_snapshot_id", "git_commit", "result_id")}
    status.update({"state": "ok", "run_started_at_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ")})
    eval_dir = tmp_path / "train_data" / "evaluation"
    eval_dir.mkdir(parents=True, exist_ok=True)
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
    manifest_file = eval_dir / "experiments" / experiment_id / "manifest.json"
    manifest = json.loads(manifest_file.read_text()) if manifest_file.exists() else None
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


def _wire(tmp_path, monkeypatch):
    eval_dir = tmp_path / "train_data" / "evaluation"
    monkeypatch.setattr(ta, "STATE_FILE", eval_dir / "tuning_state.json")
    monkeypatch.setattr(ta, "HISTORY_FILE", eval_dir / "tuning_history.jsonl")
    monkeypatch.setattr(ta, "EXPERIMENTS_DIR", eval_dir / "experiments")
    monkeypatch.setattr(ta, "_enabled", lambda: True)
    monkeypatch.setattr(ta, "_experiments_enabled", lambda: True)
    monkeypatch.setattr(ta.config, "FORECAST_EXPERIMENT_MIN_RUNTIME_HOURS", 0)
    monkeypatch.setattr(ta.config, "FORECAST_EXPERIMENT_MIN_PAIRED_SAMPLES_PER_HORIZON", 4)
    runtime_state = {"KINEMATIC_EWMA_ALPHA": 0.6}
    patched = {}
    monkeypatch.setattr(ta.runtime_config, "get", lambda name, default=None: runtime_state.get(name, default))

    def _patch(values):
        patched.update(values); runtime_state.update(values); return values
    monkeypatch.setattr(ta.runtime_config, "patch", _patch)
    return eval_dir, runtime_state, patched


def test_three_plateaus_trigger_escalation(tmp_path, monkeypatch):
    eval_dir, runtime_state, patched = _wire(tmp_path, monkeypatch)
    for _ in range(3):
        old = runtime_state["KINEMATIC_EWMA_ALPHA"]
        new = round(old - 0.05, 2) if old - 0.05 >= 0.3 else round(old + 0.05, 2)
        actual_eval_dir, experiment_id, manifest, _, _ = _apply_experiment(tmp_path, monkeypatch, old=old, new=new)
        _write_result(actual_eval_dir, experiment_id, manifest, candidate_delta=0.0)
        ta.cmd_verify()
    state = json.loads((eval_dir / "tuning_state.json").read_text())
    assert state.get("plateau_streak") == 3
    assert state.get("escalation_needed") is True
    lines = [json.loads(l) for l in (eval_dir / "tuning_history.jsonl").read_text().splitlines()]
    assert any(e.get("action") == "plateau" for e in lines)


def test_apply_is_paused_while_escalation_needed(tmp_path, monkeypatch):
    eval_dir, _, _ = _wire(tmp_path, monkeypatch)
    eval_dir.mkdir(parents=True, exist_ok=True)
    (eval_dir / "tuning_state.json").write_text(json.dumps({"escalation_needed": True, "pending": {}}))
    _, _, _, patched, _ = _apply_experiment(tmp_path, monkeypatch)
    state = json.loads((eval_dir / "tuning_state.json").read_text())
    assert state["pending"] == {}, "Apply darf bei aktiver Eskalation kein neues Experiment erzeugen"
    assert patched == {}


def test_real_improvement_resets_plateau_streak(tmp_path, monkeypatch):
    eval_dir, _, _ = _wire(tmp_path, monkeypatch)
    eval_dir.mkdir(parents=True, exist_ok=True)
    (eval_dir / "tuning_state.json").write_text(json.dumps({"plateau_streak": 2, "pending": {}}))
    actual_eval_dir, experiment_id, manifest, _, _ = _apply_experiment(tmp_path, monkeypatch)
    _write_result(actual_eval_dir, experiment_id, manifest, candidate_delta=-1.0)
    ta.cmd_verify()
    state = json.loads((eval_dir / "tuning_state.json").read_text())
    assert state["plateau_streak"] == 0
    assert "escalation_needed" not in state


def test_stall_alarm_after_14_days_without_improvement(tmp_path, monkeypatch):
    old_ts = (datetime.now(timezone.utc) - timedelta(days=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
    monkeypatch.setattr(ta, "HISTORY_FILE", tmp_path / "tuning_history.jsonl")
    (tmp_path / "tuning_history.jsonl").write_text(json.dumps({"ts": old_ts, "action": "rejected", "param": "x"}) + "\n")
    state = {}
    stalled = ta._check_stall(state)
    assert stalled is True
    assert state.get("quality_improvement_stalled") is True


def test_no_stall_alarm_with_recent_improvement(tmp_path, monkeypatch):
    recent_ts = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    monkeypatch.setattr(ta, "HISTORY_FILE", tmp_path / "tuning_history.jsonl")
    (tmp_path / "tuning_history.jsonl").write_text(json.dumps({"ts": recent_ts, "action": "improved", "param": "x"}) + "\n")
    state = {}
    stalled = ta._check_stall(state)
    assert stalled is False
    assert "quality_improvement_stalled" not in state


def test_verify_calls_check_stall_even_without_pending_experiment(tmp_path, monkeypatch):
    """B494: der Stall-Alarm darf nicht nur bei einem laufenden Experiment gepflegt
    werden — sonst faellt er in ruhigen Phasen (kein Vorschlag ueber Wochen) aus."""
    monkeypatch.setattr(ta, "STATE_FILE", tmp_path / "tuning_state.json")
    monkeypatch.setattr(ta, "HISTORY_FILE", tmp_path / "tuning_history.jsonl")
    monkeypatch.setattr(ta, "_enabled", lambda: True)
    monkeypatch.setattr(ta, "_experiments_enabled", lambda: True)
    old_ts = (datetime.now(timezone.utc) - timedelta(days=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (tmp_path / "tuning_history.jsonl").write_text(json.dumps({"ts": old_ts, "action": "rejected", "param": "x"}) + "\n")
    (tmp_path / "tuning_state.json").write_text(json.dumps({"pending": {}}))
    assert ta.cmd_verify() == 0
    state = json.loads((tmp_path / "tuning_state.json").read_text())
    assert state.get("quality_improvement_stalled") is True
