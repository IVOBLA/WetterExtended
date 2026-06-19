from pathlib import Path

TRAINING = Path("frontend/src/pages/Training.jsx").read_text(encoding="utf-8")


def test_training_page_contains_start_button():
    assert "Training jetzt starten" in TRAINING


def test_training_button_disabled_when_running():
    assert "trainingStatus?.running" in TRAINING
    assert "disabled=" in TRAINING


def test_training_start_api_is_called_on_click():
    assert "api.post('/api/training/start'" in TRAINING


def test_training_status_api_is_polled():
    assert "api.get('/api/training/status')" in TRAINING
    assert "setInterval(fetchTrainingStatus" in TRAINING


def test_training_errors_are_visible():
    assert "trainingStatus?.last_error" in TRAINING
    assert "Fehler:" in TRAINING
