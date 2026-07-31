"""Gemeinsamer Herkunftsvertrag fuer abgeleitete Qualitaetsartefakte."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "wetterextended.quality-provenance.v1"
PROVENANCE_FIELDS = (
    "schema", "generated_at_utc", "generated_by", "git_commit",
    "source_snapshot_id", "source_time_range", "source_record_count",
    "source_hash", "verification_config_hash", "matcher_contract_hash",
    "forecast_modes_included", "is_test_data",
)


def provenance(*, generated_by: str, records=None, source_snapshot_id="unknown",
               source_time_range=None, verification_config_hash="unknown",
               matcher_contract_hash="unknown", forecast_modes_included=None,
               is_test_data=False, git_commit=None) -> dict:
    records = list(records or [])
    canonical = json.dumps(records, sort_keys=True, separators=(",", ":"), default=str)
    if git_commit is None:
        try:
            git_commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
            ).strip()
        except Exception:
            git_commit = "unknown"
    return {
        "schema": SCHEMA, "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "generated_by": generated_by, "git_commit": git_commit,
        "source_snapshot_id": source_snapshot_id, "source_time_range": source_time_range or {"from": None, "to": None},
        "source_record_count": len(records), "source_hash": "sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
        "verification_config_hash": verification_config_hash, "matcher_contract_hash": matcher_contract_hash,
        "forecast_modes_included": sorted(set(forecast_modes_included or [])), "is_test_data": bool(is_test_data),
    }


def classify_artifact(value: dict) -> dict:
    missing = [field for field in PROVENANCE_FIELDS if field not in value]
    return {"comparable": not missing, "classification": "comparable" if not missing else "legacy_incomparable", "missing_fields": missing}


def atomic_write_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True); stream.flush(); os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
