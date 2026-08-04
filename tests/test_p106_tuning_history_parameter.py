"""P106: Tuning-Ergebnisse enthalten Parameter, Zielwert und Uebernahmestatus."""
from pathlib import Path

import tools.tuning_apply as ta


def _finish(tmp_path: Path, monkeypatch, pending: dict, outcome: str) -> dict:
    state_file = tmp_path / "tuning_state.json"
    history_file = tmp_path / "tuning_history.jsonl"
    entries = []
    monkeypatch.setattr(ta, "STATE_FILE", state_file)
    monkeypatch.setattr(ta, "HISTORY_FILE", history_file)
    monkeypatch.setattr(ta.runtime_config, "get", lambda name, default=None: 0.35)
    monkeypatch.setattr(ta, "_append_history", entries.append)

    assert ta._finish_experiment(
        {"pending": pending}, outcome, {"mean_delta_km": -0.5}, "test_reason"
    ) == 0
    return entries[-1]


def test_improved_history_contains_parameter_candidate_and_applied(tmp_path, monkeypatch):
    entry = _finish(tmp_path, monkeypatch, {
        "experiment_id": "exp-improved",
        "parameter": "KINEMATIC_EWMA_ALPHA",
        "candidate_value": 0.35,
    }, "improved")

    assert entry["parameter"] == "KINEMATIC_EWMA_ALPHA"
    assert entry["candidate_value"] == 0.35
    assert entry["applied"] is True


def test_plateau_history_keeps_unapplied_proposal(tmp_path, monkeypatch):
    entry = _finish(tmp_path, monkeypatch, {
        "experiment_id": "exp-plateau",
        "parameter": "KINEMATIC_EWMA_ALPHA",
        "candidate_value": 0.35,
    }, "plateau")

    assert entry["parameter"] == "KINEMATIC_EWMA_ALPHA"
    assert entry["candidate_value"] == 0.35
    assert entry["applied"] is False


def test_missing_pending_parameter_is_recorded_as_none(tmp_path, monkeypatch):
    entry = _finish(tmp_path, monkeypatch, {}, "plateau")

    assert entry["parameter"] is None
    assert entry["candidate_value"] is None
    assert entry["applied"] is False
