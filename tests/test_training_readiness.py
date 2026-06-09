"""B99: Training-Readiness-Endpoint und Schwellwerte."""
import pytest


def _cfg():
    try:
        import config
        return config
    except ImportError:
        pytest.skip("config.py nicht importierbar")


def test_min_sequences_lstm_in_config():
    assert hasattr(_cfg(), "MIN_SEQUENCES_LSTM")
    assert _cfg().MIN_SEQUENCES_LSTM >= 30, "LSTM braucht mindestens 30 Sequenzen"


def test_min_sequences_lgbm_in_config():
    assert hasattr(_cfg(), "MIN_SEQUENCES_LGBM")
    assert _cfg().MIN_SEQUENCES_LGBM >= 10


def test_lstm_threshold_higher_than_lgbm():
    assert _cfg().MIN_SEQUENCES_LSTM >= _cfg().MIN_SEQUENCES_LGBM, (
        "LSTM-Schwelle muss ≥ LightGBM-Schwelle sein"
    )


def test_training_readiness_endpoint():
    """API-Endpoint /api/training_readiness gibt korrektes Schema zurück."""
    pytest.importorskip("requests")
    import requests
    try:
        r = requests.get("http://127.0.0.1:5000/api/training_readiness", timeout=3)
    except Exception as e:
        pytest.skip(f"Flask nicht erreichbar: {e}")
    assert r.status_code == 200
    d = r.json()
    assert "current_sequences" in d
    assert "lstm" in d and "lgbm" in d
    assert "missing" in d["lstm"]
    assert isinstance(d["lstm"]["ready"], bool)
    assert d["lstm"]["missing"] >= 0
    assert d["current_sequences"] >= 0
