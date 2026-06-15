"""B154: cloud_height_from_eumetview bindet GetCapabilities und GetMap an den Breaker."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_eumetview_breaker_services():
    with open("cloud_height_from_eumetview.py", encoding="utf-8") as f:
        src = f.read()
    assert 'breaker_service="eumetview_capabilities"' in src, "GetCapabilities-Breaker fehlt"
    assert 'breaker_service="eumetview_wms"' in src, "GetMap-Breaker fehlt"


def test_getcapabilities_no_raw_requests():
    with open("cloud_height_from_eumetview.py", encoding="utf-8") as f:
        src = f.read()
    fn = src.split("def get_latest_wms_time(")[1].split("\ndef ")[0]
    assert "requests.get(" not in fn, "get_latest_wms_time nutzt noch rohes requests.get"
