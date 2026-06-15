"""B153: fetch_700hpa_wind nutzt breaker_service="openmeteo_icon_global"."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_wind_sets_breaker_service():
    with open("fetch_700hpa_wind_per_object_slim.py", encoding="utf-8") as f:
        src = f.read()
    assert 'breaker_service="openmeteo_icon_global"' in src, "breaker_service fehlt"
    assert "retry_get(" in src
