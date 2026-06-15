"""B158: Radar-Breaker — 429-Retry-After durchgereicht; Erfolg erst nach Validierung."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    with open("radar_download.py", encoding="utf-8") as f:
        return f.read()


def test_retry_after_passed_on_4xx():
    src = _src()
    assert 'Retry-After' in src, "Retry-After wird nicht ausgewertet"
    assert "retry_after=_retry_after" in src, "retry_after wird nicht an record_failure übergeben"


def test_success_only_after_validation():
    src = _src()
    # Kein record_success direkt vor dem Erfolgs-break mehr:
    assert 'record_success("arso_radar")\n            break  # Erfolg' not in src, \
        "record_success darf nicht mehr vor der Validierung (break) stehen"
    # record_success direkt vor dem finalen return True (nach dem Entpacken):
    assert 'record_success("arso_radar")\n    debug_log("Radarbild und KML erfolgreich' in src, \
        "record_success muss nach erfolgreichem Entpacken stehen"


def test_304_and_sha_success_remain():
    src = _src()
    # 304 + SHA256-identisch bleiben legitime Erfolge:
    assert src.count('record_success("arso_radar")') >= 3
