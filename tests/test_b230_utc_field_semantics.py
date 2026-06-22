# tests/test_b230_utc_field_semantics.py
"""B230 — forecast_created_at_utc / target_timestamp_utc enthalten echtes UTC
(lokale Frame-Zeit korrekt konvertiert), nicht mehr Lokalzeit unter _utc-Label."""
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import accuracy_tracker as at

_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def test_helper_summer_cest_offset():
    # CEST = UTC+2  ->  23:50 lokal == 21:50 UTC
    assert at._local_naive_to_utc_iso_z(datetime(2026, 6, 21, 23, 50, 0)) == "2026-06-21T21:50:00Z"


def test_helper_winter_cet_offset():
    # CET = UTC+1   ->  12:00 lokal == 11:00 UTC
    assert at._local_naive_to_utc_iso_z(datetime(2026, 1, 15, 12, 0, 0)) == "2026-01-15T11:00:00Z"


def test_helper_format_no_double_suffix():
    s = at._local_naive_to_utc_iso_z(datetime(2026, 6, 21, 23, 50, 0))
    assert _PATTERN.match(s)
    assert "+00:00" not in s and s.count("Z") == 1


def test_detail_record_fields_are_true_utc():
    rec = at._detail_record({}, datetime(2026, 6, 21, 23, 50, 0),
                            datetime(2026, 6, 22, 0, 0, 0), 10,
                            None, None, "miss", True, False, 10)
    assert rec["forecast_created_at_utc"] == "2026-06-21T21:50:00Z"
    assert rec["target_timestamp_utc"] == "2026-06-21T22:00:00Z"


def test_detail_record_horizon_diff_preserved():
    # target - created muss 10 min bleiben (gleiche Verschiebung)
    rec = at._detail_record({}, datetime(2026, 6, 21, 23, 50, 0),
                            datetime(2026, 6, 22, 0, 0, 0), 10,
                            None, None, "miss", True, False, 10)
    created = datetime.strptime(rec["forecast_created_at_utc"][:-1], "%Y-%m-%dT%H:%M:%S")
    target = datetime.strptime(rec["target_timestamp_utc"][:-1], "%Y-%m-%dT%H:%M:%S")
    assert (target - created).total_seconds() == 600
