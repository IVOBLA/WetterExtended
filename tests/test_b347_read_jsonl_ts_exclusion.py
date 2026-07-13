"""B347: _read_jsonl schliesst Zeilen mit unparsbarem/fehlendem Zeitstempel
konsistent aus, statt sie immer ins Fenster zu uebernehmen."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from forecast_error_diagnosis import _read_jsonl


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")


def test_row_without_timestamp_is_excluded(tmp_path):
    p = tmp_path / "details.jsonl"
    _write_jsonl(p, [{"forecast_error_km": 1.5}])  # kein Zeitstempel-Feld
    rows = _read_jsonl(p, hours=24, ts_keys=("verified_at_utc",))
    assert rows == []


def test_row_with_unparsable_timestamp_is_excluded(tmp_path):
    p = tmp_path / "details.jsonl"
    _write_jsonl(p, [{"verified_at_utc": "not-a-date", "forecast_error_km": 1.5}])
    rows = _read_jsonl(p, hours=24, ts_keys=("verified_at_utc",))
    assert rows == []


def test_row_with_recent_timestamp_is_included(tmp_path):
    p = tmp_path / "details.jsonl"
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    _write_jsonl(p, [{"verified_at_utc": recent, "forecast_error_km": 2.0}])
    rows = _read_jsonl(p, hours=24, ts_keys=("verified_at_utc",))
    assert len(rows) == 1
    assert rows[0]["forecast_error_km"] == 2.0


def test_row_with_old_timestamp_is_excluded(tmp_path):
    p = tmp_path / "details.jsonl"
    old = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat().replace("+00:00", "Z")
    _write_jsonl(p, [{"verified_at_utc": old, "forecast_error_km": 3.0}])
    rows = _read_jsonl(p, hours=24, ts_keys=("verified_at_utc",))
    assert rows == []


def test_mixed_batch_keeps_only_valid_recent_rows(tmp_path):
    p = tmp_path / "details.jsonl"
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    old = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat().replace("+00:00", "Z")
    _write_jsonl(p, [
        {"verified_at_utc": recent, "forecast_error_km": 1.0},
        {"verified_at_utc": old, "forecast_error_km": 2.0},
        {"forecast_error_km": 3.0},
        {"verified_at_utc": "garbage", "forecast_error_km": 4.0},
    ])
    rows = _read_jsonl(p, hours=24, ts_keys=("verified_at_utc",))
    assert len(rows) == 1
    assert rows[0]["forecast_error_km"] == 1.0
