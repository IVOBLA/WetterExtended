# tests/test_b227_utc_iso_z.py
"""B227 — utc_iso_z erzeugt gueltiges UTC-ISO mit genau einem 'Z', nie '+00:00Z'."""
import os
import re
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import utc_iso_z

_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _assert_valid(s):
    assert _PATTERN.match(s), f"Ungueltiges Format: {s!r}"
    assert "+00:00" not in s, f"Doppelte Zeitzone: {s!r}"
    assert s.count("Z") == 1, f"Mehr als ein 'Z': {s!r}"
    # muss nach Strippen des Z als UTC parsebar sein
    datetime.strptime(s[:-1], "%Y-%m-%dT%H:%M:%S")


def test_none_is_current_utc():
    _assert_valid(utc_iso_z())


def test_aware_utc():
    dt = datetime(2026, 6, 21, 21, 28, 12, tzinfo=timezone.utc)
    s = utc_iso_z(dt)
    _assert_valid(s)
    assert s == "2026-06-21T21:28:12Z"


def test_aware_non_utc_is_converted():
    # CEST = UTC+2 -> 23:28 lokal == 21:28 UTC
    cest = timezone(timedelta(hours=2))
    dt = datetime(2026, 6, 21, 23, 28, 12, tzinfo=cest)
    s = utc_iso_z(dt)
    _assert_valid(s)
    assert s == "2026-06-21T21:28:12Z"


def test_naive_is_treated_as_utc():
    dt = datetime(2026, 6, 21, 21, 28, 12)
    s = utc_iso_z(dt)
    _assert_valid(s)
    assert s == "2026-06-21T21:28:12Z"


def test_no_double_suffix_regression():
    # exakt der Bugfall: aware-now darf nie '+00:00Z' liefern
    s = utc_iso_z(datetime.now(timezone.utc))
    assert "+00:00Z" not in s
    _assert_valid(s)
