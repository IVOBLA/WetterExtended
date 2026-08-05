from pathlib import Path

import tools.tuning_apply as ta


def _capture_history(monkeypatch):
    history = []
    monkeypatch.setattr(ta, "_atomic_json", lambda *_args: None)
    monkeypatch.setattr(ta, "_append_history", history.append)
    return history


def test_finish_experiment_uses_incumbent_value_after_promotion(monkeypatch):
    history = _capture_history(monkeypatch)
    monkeypatch.setattr(ta.runtime_config, "get", lambda *_args: 0.35)
    state = {"pending": {
        "experiment_id": "experiment-1",
        "parameter": "KINEMATIC_EWMA_ALPHA",
        "incumbent_value": 0.20,
        "candidate_value": 0.35,
    }}

    assert ta._finish_experiment(state, "improved", {}, "promoted") == 0

    assert history[-1]["old_value"] == 0.20
    assert history[-1]["old_value"] != 0.35


def test_finish_experiment_without_incumbent_value(monkeypatch):
    history = _capture_history(monkeypatch)

    assert ta._finish_experiment({"pending": {}}, "rejected", {}, "no gain") == 0

    assert history[-1]["old_value"] is None


def test_ai_suggestions_has_single_current_history_block():
    """B508: P107 ersetzte die Historienliste durch 'Aktuell getunte Werte' /
    'Letztes Ergebnis' — der urspruengliche Pruefzweck (keine Duplizierung der
    Tuning-Anzeige) gilt jetzt fuer die neuen Bezeichner."""
    source = Path("frontend/src/pages/AiSuggestions.jsx").read_text(encoding="utf-8")

    assert source.count("Aktuell getunte Werte") == 1
    assert source.count("Letztes Ergebnis") == 1
    assert "Letzte Tuning-Aktionen" not in source
    assert "Letzte automatische Aenderungen" not in source
