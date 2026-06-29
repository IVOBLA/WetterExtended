"""B261: log_api_failure schreibt keine Test-Telemetrie-Einträge."""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import debug_utils


def _read_health(path: str) -> list:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_sentinel_service_t_wird_verworfen(tmp_path, monkeypatch):
    """service='t' landet nicht in api_health.jsonl."""
    log = str(tmp_path / "api_health.jsonl")
    monkeypatch.setattr(debug_utils, "_API_HEALTH_FILE", log)
    debug_utils.log_api_failure("t", "https://example.invalid", "test-error")
    assert _read_health(log) == [], "service='t' darf nicht geloggt werden"


def test_sentinel_url_example_invalid_wird_verworfen(tmp_path, monkeypatch):
    """url='https://example.invalid' landet nicht in api_health.jsonl."""
    log = str(tmp_path / "api_health.jsonl")
    monkeypatch.setattr(debug_utils, "_API_HEALTH_FILE", log)
    debug_utils.log_api_failure("some_service", "https://example.invalid/path", "err")
    assert _read_health(log) == []


def test_echter_service_wird_geloggt(tmp_path, monkeypatch):
    """Echte API-Fehler landen weiterhin in api_health.jsonl."""
    log = str(tmp_path / "api_health.jsonl")
    monkeypatch.setattr(debug_utils, "_API_HEALTH_FILE", log)
    debug_utils.log_api_failure(
        "Open-Meteo-icon_d2",
        "https://api.open-meteo.com/v1/forecast",
        "http-429",
        fallback_used=True,
        http_status=429,
    )
    entries = _read_health(log)
    assert len(entries) == 1
    assert entries[0]["service"] == "Open-Meteo-icon_d2"
    assert entries[0]["http_status"] == 429


def test_regression_service_t_mit_echtem_url_auch_gefiltert(tmp_path, monkeypatch):
    """service='t' mit echter URL: trotzdem kein Eintrag."""
    log = str(tmp_path / "api_health.jsonl")
    monkeypatch.setattr(debug_utils, "_API_HEALTH_FILE", log)
    debug_utils.log_api_failure("t", "https://api.open-meteo.com/v1/forecast", "err")
    assert _read_health(log) == []
