"""B152: blitz_api nutzt breaker_service="blitzortung_last_strikes"."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_blitz_sets_breaker_service():
    with open("blitz_api.py", encoding="utf-8") as f:
        src = f.read()
    assert 'breaker_service="blitzortung_last_strikes"' in src, "breaker_service fehlt"
    assert "retry_get(" in src
