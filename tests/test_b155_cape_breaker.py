"""B155: assign_cape_from_forecast nutzt retry_get + breaker_service="geosphere_cape"."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_cape_breaker_and_no_raw_request():
    with open("assign_cape_from_forecast.py", encoding="utf-8") as f:
        src = f.read()
    assert 'breaker_service="geosphere_cape"' in src, "breaker_service fehlt"
    fn = src.split("def fetch_or_use_latest_geojson(")[1].split("\ndef ")[0]
    assert "requests.get(" not in fn, "fetch_or_use_latest_geojson nutzt noch rohes requests.get"
