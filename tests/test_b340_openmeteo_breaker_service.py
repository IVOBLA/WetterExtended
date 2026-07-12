"""B340: Fünf Open-Meteo-Fetcher nutzen breaker_service="openmeteo_forecast"."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_synoptic_features_uses_breaker_service():
    src = _read("fetch_synoptic_features.py")
    assert 'service="Open-Meteo-synoptic", breaker_service="openmeteo_forecast"' in src


def test_openmeteo_extended_uses_breaker_service():
    src = _read("fetch_openmeteo_extended.py")
    for service_name in (
        "openmeteo_extended_15min",
        "openmeteo_extended_pressure",
        "openmeteo_extended_lpi",
        "openmeteo_extended_gfs_conv",
    ):
        needle = f'service="{service_name}", timeout=_TIMEOUT, breaker_service="openmeteo_forecast"'
        assert needle in src, f"breaker_service fehlt für {service_name}"
