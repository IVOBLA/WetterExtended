"""B160: auch der GetCapabilities-Re-Fetch im B125-Loop nutzt den Breaker."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_caps_loop_refetch_has_breaker():
    with open("cloud_height_from_eumetview.py", encoding="utf-8") as f:
        src = f.read()
    # Kein retry_get auf EUMETView-WMS-Caps mehr OHNE breaker_service:
    assert 'retry_get(url, service="EUMETView-WMS-Caps", timeout=30)' not in src, \
        "Re-Fetch im Loop ohne breaker_service noch vorhanden"
    # Beide GetCapabilities-Aufrufe (Erst-Request B154 + Loop-Re-Fetch B160) gebunden:
    assert src.count('breaker_service="eumetview_capabilities"') >= 2, \
        "nicht beide Capabilities-Aufrufe angebunden"
