#!/usr/bin/env python3
"""Validiert forecast_error_details.jsonl ohne externe Requests."""
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


def _read_jsonl(path: Path):
    if not path.exists():
        return [], Counter({"missing_file": 1})
    rows = []
    warnings = Counter()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except Exception:
            warnings["bad_json_line"] += 1
            continue
        if isinstance(rec, dict):
            rows.append(rec)
        else:
            warnings["non_object_line"] += 1
    return rows, warnings


def summarize(path: Path) -> dict:
    rows, warnings = _read_jsonl(path)
    invalid = Counter()
    valid = []
    for row in rows:
        ok, reason = is_valid_forecast_error_detail(row)
        if ok:
            valid.append(row)
        else:
            invalid[reason or "invalid_detail"] += 1
    valid_times = [_parse_ts(r.get("verified_at_utc")) or _parse_ts(r.get("target_timestamp_utc")) or _parse_ts(r.get("forecast_created_at_utc")) for r in valid]
    valid_times = [t for t in valid_times if t is not None]
    sources = Counter(str(r.get("kinematic_source") or "unknown") for r in valid)
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
        "of_available_1": sum(1 for r in valid if int(r.get("of_available", 0) or 0) == 1),
        "top_kinematic_source": sources.most_common(10),
        "warnings": dict(warnings),
        "synthetic_data_warning": invalid.get("synthetic_or_test_fixture", 0) > 0,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default="train_data/evaluation/forecast_error_details.jsonl")
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)
    summary = summarize(Path(ns.path))
    if ns.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(f"Gesamtzahl Details: {summary['details_total']}")
        print(f"Valide Details: {summary['details_valid']}")
        print(f"Ungültige Details: {summary['details_invalid']} {summary['invalid_detail_counts']}")
        print(f"Zeitspanne valide Details: {summary['valid_time_span']['from_utc']} .. {summary['valid_time_span']['to_utc']}")
        print(f"Details mit of_available=1: {summary['of_available_1']}")
        print(f"Top kinematic_source: {summary['top_kinematic_source']}")
        if summary["synthetic_data_warning"]:
            print("WARNUNG: synthetische/Test-Fixture-Daten gefunden.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
