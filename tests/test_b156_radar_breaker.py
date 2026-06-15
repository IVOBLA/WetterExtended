"""B156: radar_download bindet den Circuit-Breaker explizit an (Service arso_radar)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_radar_breaker_calls_present():
    with open("radar_download.py", encoding="utf-8") as f:
        src = f.read()
    assert 'is_open("arso_radar")' in src, "is_open-Gate fehlt"
    assert src.count('record_success("arso_radar")') >= 3, "record_success an 304/SHA256/200 fehlt"
    assert 'record_failure("arso_radar"' in src, "record_failure fehlt"


def test_radar_keeps_304_and_retry_loop():
    with open("radar_download.py", encoding="utf-8") as f:
        src = f.read()
    assert "if response.status_code == 304:" in src, "304-Logik darf nicht verloren gehen"
    assert "_MAX_RETRIES" in src, "eigene Retry-Schleife bleibt"
