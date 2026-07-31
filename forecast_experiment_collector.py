"""Begrenzter produktiver Store und Collector für Shadow-Forecasts."""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from experiment_contract import EXPERIMENT_SCHEMA, stable_hash

ROOT = Path(__file__).resolve().parent
EVAL_DIR = ROOT / "train_data" / "evaluation"
EXPERIMENTS_DIR = EVAL_DIR / "experiments"
VERIFICATION_DB = EVAL_DIR / "forecast_verification.sqlite3"


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


def append_variant(experiment_id: str, record: dict, *, max_records: int = 20000) -> None:
    """Append unter Lock; Rotation hält den Pi-Store begrenzt."""
    import fcntl
    path = EXPERIMENTS_DIR / experiment_id / "forecast_variants.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+", encoding="utf-8") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
        stream.flush(); os.fsync(stream.fileno())
        stream.seek(0); lines = stream.readlines()
        if len(lines) > max_records:
            stream.seek(0); stream.truncate(); stream.writelines(lines[-max_records:])


def _variants(path: Path) -> dict[tuple[str, str], dict]:
    result = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line); key = (row["case_key"], row["variant_role"])
            if key in result: raise ValueError("duplicate variant/case_key")
            result[key] = row
    return result


def _distance_km(a_lat, a_lon, b_lat, b_lon) -> float:
    from math import asin, cos, radians, sin, sqrt
    p1, p2 = radians(float(a_lat)), radians(float(b_lat)); dp = p2 - p1
    dl = radians(float(b_lon) - float(a_lon))
    return 6371.0088 * 2 * asin(sqrt(sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2))


def collect_experiment(experiment_id: str, *, verification_db: Path | None = None) -> dict:
    """Koppelt beide Varianten an genau die finale Gold-Sicht aus Prompt 1."""
    directory = EXPERIMENTS_DIR / experiment_id
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    variants = _variants(directory / "forecast_variants.jsonl")
    db = verification_db or VERIFICATION_DB
    with sqlite3.connect(db) as con:
        actual_rows = con.execute("SELECT case_key,payload_json FROM final_actuals ORDER BY case_key").fetchall()
    pairs, missing, rejected, fallback, excluded = [], 0, 0, 0, 0
    eligible = 0
    for case_key, payload in actual_rows:
        actual = json.loads(payload)
        if not actual.get("eligible_for_model_tuning", False): excluded += 1; continue
        if actual.get("verification_state") != "final" or actual.get("match_class") not in {
                "exact_id", "exact_cell_id", "lineage_confirmed"}: excluded += 1; continue
        inc = variants.get((case_key, "incumbent"))
        if not inc: continue
        eligible += 1
        cand = variants.get((case_key, "candidate"))
        if not cand: missing += 1; continue
        if cand.get("rejected"): rejected += 1; continue
        fallback += int(bool(cand.get("fallback")))
        row = {
            "case_key": case_key, "horizon_min": int(inc["horizon_min"]),
            "event_id": actual.get("event_id"), "cell_id": actual.get("cell_id"),
            "incumbent_error_km": _distance_km(inc["lat"], inc["lon"], actual["actual_lat"], actual["actual_lon"]),
            "candidate_error_km": _distance_km(cand["lat"], cand["lon"], actual["actual_lat"], actual["actual_lon"]),
            "state": "final", "eligible_for_model_tuning": True, "match_type": actual["match_class"],
            "incumbent_actual_id": actual.get("matched_object_id"), "candidate_actual_id": actual.get("matched_object_id"),
            "incumbent_actual_lat": actual.get("actual_lat"), "candidate_actual_lat": actual.get("actual_lat"),
            "incumbent_actual_lon": actual.get("actual_lon"), "candidate_actual_lon": actual.get("actual_lon"),
        }
        for field in ("experiment_id", "policy_hash", "verification_config_hash", "matcher_contract_hash",
                      "forecast_variant_id_incumbent", "forecast_variant_id_candidate"):
            row[field] = manifest[field]
        pairs.append(row)
    pairs.sort(key=lambda r: r["case_key"])
    sample_set_id = stable_hash([{"case_key": r["case_key"], "verification_config_hash": r["verification_config_hash"],
                                  "matcher_contract_hash": r["matcher_contract_hash"]} for r in pairs])
    result = {key: manifest[key] for key in ("experiment_id", "analysis_run_id", "source_snapshot_id", "git_commit",
              "policy_hash", "verification_config_hash", "matcher_contract_hash", "forecast_code_hash")}
    result.update({"schema": EXPERIMENT_SCHEMA, "sample_set_id": sample_set_id,
                   "parameter_set_hash": manifest["candidate_parameter_set_hash"],
                   "incumbent_parameter_set_hash": manifest["incumbent_parameter_set_hash"],
                   "started_at_utc": manifest["created_at_utc"],
                   "closed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                   "paired_cases": pairs, "eligible_case_count": eligible,
                   "candidate_missing_count": missing, "candidate_rejected_count": rejected,
                   "candidate_fallback_count": fallback, "incumbent_missing_count": 0,
                   "data_quality_excluded_count": excluded, "producer": "forecast_experiment_collector"})
    with open(directory / "paired_cases.jsonl.tmp", "w", encoding="utf-8") as out:
        for row in pairs: out.write(json.dumps(row, sort_keys=True) + "\n")
    os.replace(directory / "paired_cases.jsonl.tmp", directory / "paired_cases.jsonl")
    _atomic_json(directory / "result.json", result)
    _atomic_json(directory / "status.json", {"experiment_id": experiment_id, "state": "collected",
                                               "sample_set_id": sample_set_id})
    return result
