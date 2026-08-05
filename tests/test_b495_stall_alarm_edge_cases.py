"""B495: Zwei Codex-Review-Kommentare zu B494. (1) Legacy-'accepted'-Eintraege aus
der Zeit vor dem P104/P105-Experiment-Umbau duerfen nicht ignoriert werden, sonst
loest ein Upgrade sofort einen falschen Stall-Alarm aus. (2) Ein im selben --verify
gesetztes Stall-Flag muss bei sofortigem Erfolg ('improved') sofort wieder geloescht
werden, nicht erst am naechsten Tag."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tools.tuning_apply as ta  # noqa: E402


def test_legacy_accepted_entry_counts_as_improvement(tmp_path, monkeypatch):
    monkeypatch.setattr(ta, "HISTORY_FILE", tmp_path / "tuning_history.jsonl")
    recent_ts = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    old_ts = (datetime.now(timezone.utc) - timedelta(days=40)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (tmp_path / "tuning_history.jsonl").write_text(
        json.dumps({"ts": old_ts, "action": "rejected", "param": "x"}) + "\n"
        + json.dumps({"ts": recent_ts, "action": "accepted", "param": "x"}) + "\n")
    assert ta._last_accepted_ts() == recent_ts


def test_upgrade_with_recent_legacy_improvement_does_not_false_alarm(tmp_path, monkeypatch):
    monkeypatch.setattr(ta, "HISTORY_FILE", tmp_path / "tuning_history.jsonl")
    recent_ts = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ancient_ts = (datetime.now(timezone.utc) - timedelta(days=400)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (tmp_path / "tuning_history.jsonl").write_text(
        json.dumps({"ts": ancient_ts, "action": "rejected", "param": "x"}) + "\n"
        + json.dumps({"ts": recent_ts, "action": "accepted", "param": "x"}) + "\n")
    state = {}
    stalled = ta._check_stall(state)
    assert stalled is False
    assert "quality_improvement_stalled" not in state


def test_finish_experiment_clears_stall_flag_on_immediate_improvement(tmp_path, monkeypatch):
    # B507: _finish_experiment() schreibt unbedingt nach STATE_FILE/HISTORY_FILE —
    # ohne Isolation landen diese Testwerte in den echten Produktionsdateien.
    monkeypatch.setattr(ta, "HISTORY_FILE", tmp_path / "tuning_history.jsonl")
    monkeypatch.setattr(ta, "STATE_FILE", tmp_path / "tuning_state.json")
    state = {"quality_improvement_stalled": True, "pending": {"experiment_id": "e1"}}
    ta._finish_experiment(state, "improved", {"mean_delta_km": -1.0}, "statistically_significant_improvement")
    assert "quality_improvement_stalled" not in state


def test_finish_experiment_keeps_stall_flag_on_plateau(tmp_path, monkeypatch):
    """Regression: das Loeschen darf nur bei outcome == 'improved' passieren, nicht
    bei jedem Verify-Ausgang."""
    # B507: siehe Kommentar in der vorherigen Testfunktion.
    monkeypatch.setattr(ta, "HISTORY_FILE", tmp_path / "tuning_history.jsonl")
    monkeypatch.setattr(ta, "STATE_FILE", tmp_path / "tuning_state.json")
    state = {"quality_improvement_stalled": True, "pending": {"experiment_id": "e1"}, "plateau_streak": 0}
    ta._finish_experiment(state, "plateau", {"mean_delta_km": 0.0}, "acceptance_criteria_not_met")
    assert state.get("quality_improvement_stalled") is True
