"""B157: fetch_arome_openmeteo bindet icon_d2 + icon_eu_li an den Breaker; kein Doppel-Log."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    with open("fetch_arome_openmeteo.py", encoding="utf-8") as f:
        return f.read()


def test_breaker_services_present():
    src = _src()
    assert 'breaker_service="openmeteo_icon_d2"' in src, "icon_d2-Breaker fehlt"
    assert 'breaker_service="openmeteo_icon_eu_li"' in src, "icon_eu_li-Breaker fehlt"


def test_no_double_log_in_main_except():
    src = _src()
    fn = src.split("def assign_arome_to_objects(")[1].split("\ndef ")[0]
    assert 'f"{type(exc).__name__}: {exc}", fallback_used=True' not in fn, \
        "Doppel-Log im icon_d2-except noch vorhanden"


def test_canonical_service_name():
    src = _src()
    # icon_d2-Request läuft jetzt unter kanonischem Namen:
    assert 'service="openmeteo_icon_d2"' in src
