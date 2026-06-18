#!/usr/bin/env python3
"""Diagnose-Tool für B215 Forecast-Error-Detail-Validation."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from forecast_error_diagnosis import _parse_ts, is_valid_forecast_error_detail  # noqa: E402


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if isinstance(rec, dict):
            rows.append(rec)
    return rows


def build_report(path: Path) -> dict:
    rows = _read_jsonl(path)
    invalid = Counter()
    valid = []
    for row in rows:
        ok, reason = is_valid_forecast_error_detail(row)
        if ok:
            valid.append(row)
        else:
            invalid[reason or "invalid_time_order"] += 1
    valid_times = [
        ts for row in valid
        for ts in [_parse_ts(row.get("verified_at_utc")) or _parse_ts(row.get("target_timestamp_utc"))]
        if ts is not None
    ]
    sources = Counter(str(row.get("kinematic_source") or "unknown") for row in valid)
    return {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "path": str(path),
        "details_total": len(rows),
        "details_valid": len(valid),
        "details_invalid": sum(invalid.values()),
        "invalid_detail_counts": dict(invalid),
        "valid_time_span": {
            "from_utc": min(valid_times).isoformat().replace("+00:00", "Z") if valid_times else None,
            "to_utc": max(valid_times).isoformat().replace("+00:00", "Z") if valid_times else None,
        },
        "of_available_1": sum(1 for row in valid if int(row.get("of_available", 0) or 0) == 1),
        "top_kinematic_source": sources.most_common(10),
        "warning": "synthetische Daten gefunden" if invalid.get("synthetic_or_test_fixture", 0) else None,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default="train_data/evaluation/forecast_error_details.jsonl")
    ns = ap.parse_args(argv)
    print(json.dumps(build_report(Path(ns.path)), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
