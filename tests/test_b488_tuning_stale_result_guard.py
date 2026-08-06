"""B488/B494: Apply darf nur auf einem frischen, erfolgreichen und noch nicht
konsumierten Analyse-Lauf ein Shadow-Experiment erzeugen. Seit dem Experiment-Umbau
laeuft die Konsum-Sperre ueber result_id-Bindung statt last_applied_success_date."""
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tools.tuning_apply as ta  # noqa: E402


def _wire(tmp_path, monkeypatch):
    eval_dir = tmp_path / "train_data" / "evaluation"
    eval_dir.mkdir(parents=True)
    monkeypatch.setattr(ta, "_enabled", lambda: True)
    monkeypatch.setattr(ta, "_experiments_enabled", lambda: True)
    monkeypatch.setattr(ta, "EVAL_DIR", eval_dir)
    monkeypatch.setattr(ta, "STATE_FILE", eval_dir / "tuning_state.json")
    monkeypatch.setattr(ta, "HISTORY_FILE", eval_dir / "tuning_history.jsonl")
    monkeypatch.setattr(ta, "RESULT_FILE", eval_dir / "analysis_result.json")
    monkeypatch.setattr(ta, "STATUS_FILE", eval_dir / "local_analysis_status.json")
    monkeypatch.setattr(ta, "EXPERIMENTS_DIR", eval_dir / "experiments")
    monkeypatch.setattr(ta.runtime_config, "get", lambda k, d=None: d)
    return eval_dir


def _valid_payload_and_status():
    payload = {
        "schema": "wetterextended.local-analysis.v2", "analysis_run_id": str(uuid.uuid4()),
        "source_snapshot_id": "sha256:a", "git_commit": "abc", "result_id": str(uuid.uuid4()),
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tuning_proposals": [{
            "experiment_id": str(uuid.uuid4()), "target_system": "kinematic",
            "target_horizons": [10], "parameter": "KINEMATIC_EWMA_ALPHA",
            "old_value": 0.6, "new_value": 0.55, "code_ref": "prediction.py:_append_kinematic",
            "evidence_refs": ["case:1"], "expected_effect": {"metric": "mae_km", "direction": "decrease", "minimum_change": 0.05},
            "minimum_paired_samples": {"10": 4}, "maximum_runtime_hours": 48,
        }],
    }
    started = datetime.now(timezone.utc) - timedelta(minutes=1)
    status = {k: payload[k] for k in ("analysis_run_id", "source_snapshot_id", "git_commit", "result_id")}
    status.update({"state": "ok", "run_started_at_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ")})
    return payload, status


def test_apply_skips_when_last_run_failed(tmp_path, monkeypatch):
    eval_dir = _wire(tmp_path, monkeypatch)
    (eval_dir / "local_analysis_status.json").write_text(json.dumps({"state": "failed"}))
    (eval_dir / "analysis_result.json").write_text(json.dumps({"tuning_proposals": []}))
    patched = {}
    monkeypatch.setattr(ta.runtime_config, "patch", lambda d: patched.update(d) or d)
    assert ta.cmd_apply() == 0
    assert patched == {}


def test_apply_creates_shadow_when_run_is_fresh_and_valid(tmp_path, monkeypatch):
    eval_dir = _wire(tmp_path, monkeypatch)
    payload, status = _valid_payload_and_status()
    (eval_dir / "local_analysis_status.json").write_text(json.dumps(status))
    (eval_dir / "analysis_result.json").write_text(json.dumps(payload))
    patched = {}
    monkeypatch.setattr(ta.runtime_config, "patch", lambda d: patched.update(d) or d)
    assert ta.cmd_apply() == 0
    assert patched == {}  # Apply patcht nie direkt — nur Shadow-Erzeugung
    state = json.loads((eval_dir / "tuning_state.json").read_text())
    assert state["last_consumed_result_id"] == payload["result_id"]
    assert state["pending"]["state"] == "shadow_collecting"


def test_apply_skips_when_result_already_consumed(tmp_path, monkeypatch):
    eval_dir = _wire(tmp_path, monkeypatch)
    payload, status = _valid_payload_and_status()
    (eval_dir / "local_analysis_status.json").write_text(json.dumps(status))
    (eval_dir / "analysis_result.json").write_text(json.dumps(payload))
    (eval_dir / "tuning_state.json").write_text(json.dumps(
        {"baselines": {}, "pending": {}, "last_consumed_result_id": payload["result_id"]}))
    patched = {}
    monkeypatch.setattr(ta.runtime_config, "patch", lambda d: patched.update(d) or d)
    assert ta.cmd_apply() == 0
    assert patched == {}
