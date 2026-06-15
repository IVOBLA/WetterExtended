"""B159: kein Doppel-Logging im CAPE-Fetch-except (retry_get loggt bereits)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_no_double_log_in_fetch_except():
    with open("assign_cape_from_forecast.py", encoding="utf-8") as f:
        src = f.read()
    fn = src.split("def fetch_or_use_latest_geojson(")[1].split("\ndef ")[0]
    # Im CAPE-Fetch darf kein caller-seitiges log_api_failure mehr stehen:
    assert 'f"{type(e).__name__}: {e}", fallback_used=True' not in fn, \
        "Doppel-Log im except noch vorhanden"
    # Der eigentliche Fetch nutzt weiterhin den Breaker:
    assert 'breaker_service="geosphere_cape"' in fn


def test_other_cape_failure_logs_remain():
    with open("assign_cape_from_forecast.py", encoding="utf-8") as f:
        src = f.read()
    # Die inhaltlichen GeoSphere-CAPE-Logs (no-forecast/no-valid-data/geojson-fetch-failed)
    # bleiben erhalten — sie werden nicht von retry_get abgedeckt.
    assert 'log_api_failure("GeoSphere-CAPE"' in src
