"""B488: cmd_apply() wandte tuning_proposals unabhaengig davon an, ob der zugrunde
liegende lokale KI-Lauf ueberhaupt erfolgreich und aktuell war. Diese Tests verankern
Freshness- (nur state=ok) und Idempotenz-Pruefung (kein doppeltes Apply desselben Laufs)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tools.tuning_apply as ta  # noqa: E402


def _wire(tmp_path, monkeypatch):
    eval_dir = tmp_path / "train_data" / "evaluation"
    eval_dir.mkdir(parents=True)
    monkeypatch.setattr(ta, "_enabled", lambda: True)
    monkeypatch.setattr(ta, "EVAL_DIR", eval_dir)
    monkeypatch.setattr(ta, "STATE_FILE", eval_dir / "tuning_state.json")
    monkeypatch.setattr(ta, "HISTORY_FILE", eval_dir / "tuning_history.jsonl")
    monkeypatch.setattr(ta, "RESULT_FILE", eval_dir / "analysis_result.json")
    monkeypatch.setattr(ta, "DRIFT_FILE", eval_dir / "drift_status.json")
    monkeypatch.setattr(ta, "STATUS_FILE", eval_dir / "local_analysis_status.json")
    monkeypatch.setattr(ta.runtime_config, "get", lambda k, d=None: d)
    return eval_dir


def test_apply_skips_when_last_run_failed(tmp_path, monkeypatch):
    eval_dir = _wire(tmp_path, monkeypatch)
    (eval_dir / "local_analysis_status.json").write_text(json.dumps(
        {"state": "failed", "last_success_date": "2026-07-29"}))
    (eval_dir / "analysis_result.json").write_text(json.dumps(
        {"tuning_proposals": {"KINEMATIC_EWMA_ALPHA": {"value": 0.5, "reason": "t"}}}))
    patched = {}
    monkeypatch.setattr(ta.runtime_config, "patch", lambda d: patched.update(d) or d)
    assert ta.cmd_apply() == 0
    assert patched == {}


def test_apply_runs_when_last_run_succeeded_today(tmp_path, monkeypatch):
    eval_dir = _wire(tmp_path, monkeypatch)
    (eval_dir / "local_analysis_status.json").write_text(json.dumps(
        {"state": "ok", "last_success_date": "2026-07-31"}))
    (eval_dir / "drift_status.json").write_text(json.dumps(
        {"quality_target_by_horizon": {"10": {"actual_mae_km": 3.0}}}))
    (eval_dir / "analysis_result.json").write_text(json.dumps(
        {"tuning_proposals": {"KINEMATIC_EWMA_ALPHA": {"value": 0.5, "reason": "t"}}}))
    patched = {}
    monkeypatch.setattr(ta.runtime_config, "patch", lambda d: patched.update(d) or d)
    assert ta.cmd_apply() == 0
    assert patched.get("KINEMATIC_EWMA_ALPHA") == 0.5
    st = json.loads((eval_dir / "tuning_state.json").read_text())
    assert st["last_applied_success_date"] == "2026-07-31"


def test_apply_skips_when_result_already_consumed(tmp_path, monkeypatch):
    eval_dir = _wire(tmp_path, monkeypatch)
    (eval_dir / "local_analysis_status.json").write_text(json.dumps(
        {"state": "ok", "last_success_date": "2026-07-31"}))
    (eval_dir / "tuning_state.json").write_text(json.dumps(
        {"baselines": {}, "pending": {}, "last_applied_success_date": "2026-07-31"}))
    (eval_dir / "analysis_result.json").write_text(json.dumps(
        {"tuning_proposals": {"KINEMATIC_EWMA_ALPHA": {"value": 0.5, "reason": "t"}}}))
    patched = {}
    monkeypatch.setattr(ta.runtime_config, "patch", lambda d: patched.update(d) or d)
    assert ta.cmd_apply() == 0
    assert patched == {}
