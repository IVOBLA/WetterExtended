"""
B308: evaluate_on_recent_adaptive erweitert das Evaluationsfenster schrittweise,
wenn im 24h-Startfenster zu wenige verifizierte Samples vorliegen (z. B. ruhige
Wetterlagen), statt die Modell-Promotion dauerhaft an einer harten Coverage-Grenze
scheitern zu lassen. MIN_SAMPLES_FOR_PROMOTION selbst bleibt unveraendert streng.
"""
import pytest

mt = pytest.importorskip("model_training")


def test_returns_immediately_if_start_window_has_enough_samples(monkeypatch):
    calls = []

    def _fake(model_dir, hours=24):
        calls.append(hours)
        return {"mae_total": 3.0, "samples": 80}

    monkeypatch.setattr(mt, "evaluate_on_recent", _fake)
    result = mt.evaluate_on_recent_adaptive("dummy_dir", min_samples=50, max_hours=168)
    assert calls == [24]
    assert result["eval_window_hours"] == 24
    assert result["samples"] == 80


def test_widens_window_when_start_window_insufficient(monkeypatch):
    calls = []

    def _fake(model_dir, hours=24):
        calls.append(hours)
        samples_by_hours = {24: 4, 48: 20, 96: 55}
        return {"mae_total": 3.0, "samples": samples_by_hours.get(hours, 55)}

    monkeypatch.setattr(mt, "evaluate_on_recent", _fake)
    result = mt.evaluate_on_recent_adaptive("dummy_dir", min_samples=50, max_hours=168)
    assert calls == [24, 48, 96]
    assert result["eval_window_hours"] == 96
    assert result["samples"] == 55


def test_stops_at_max_hours_even_if_still_insufficient(monkeypatch):
    calls = []

    def _fake(model_dir, hours=24):
        calls.append(hours)
        return {"mae_total": 3.0, "samples": 4}  # bleibt immer knapp

    monkeypatch.setattr(mt, "evaluate_on_recent", _fake)
    result = mt.evaluate_on_recent_adaptive("dummy_dir", min_samples=50, max_hours=100)
    assert calls == [24, 48, 96, 100]
    assert result["eval_window_hours"] == 100
    assert result["samples"] == 4


def test_uses_module_defaults_when_not_specified(monkeypatch):
    calls = []

    def _fake(model_dir, hours=24):
        calls.append(hours)
        return {"mae_total": 3.0, "samples": 5}

    monkeypatch.setattr(mt, "evaluate_on_recent", _fake)
    result = mt.evaluate_on_recent_adaptive("dummy_dir")
    assert calls[0] == 24
    assert calls[-1] == mt.MODEL_PROMOTION_EVAL_MAX_HOURS


def test_min_samples_threshold_unchanged():
    # B308 senkt die Qualitaetsschwelle NICHT — nur das Zeitfenster wird erweitert.
    assert mt.MIN_SAMPLES_FOR_PROMOTION == 50
