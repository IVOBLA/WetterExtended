"""Transactional closed-loop storage for forecast verification.

The legacy JSONL detail stream remains an immutable raw input.  This module owns
the authoritative latest view and its append-only revision ledger.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "forecast-verification/v1"
STATES = frozenset({"pending", "provisional", "final", "superseded", "invalid"})
MATCH_CLASSES = frozenset({"exact_id", "exact_cell_id", "lineage_confirmed", "ambiguous_nearest", "no_match", "target_frame_missing", "target_frame_empty", "match_rejected_speed", "match_rejected_core"})
GOLD_MATCH_CLASSES = frozenset({"exact_id", "exact_cell_id", "lineage_confirmed"})
CASE_FIELDS = ("forecast_created_at_utc", "target_timestamp_utc", "horizon_min", "origin_object_id", "origin_cell_id", "origin_radar_track_id", "forecast_source_frame_id")


def _canonical(values: Mapping[str, Any], fields: tuple[str, ...]) -> str:
    return json.dumps([values.get(k) if values.get(k) not in ("​",) else None for k in fields], ensure_ascii=False, separators=(",", ":"), default=str)


def build_case_key(record: Mapping[str, Any]) -> str:
    """Stable identity: deliberately excludes actual, matcher and run time."""
    return "case:" + hashlib.sha256(_canonical(record, CASE_FIELDS).encode()).hexdigest()


def build_variant_key(record: Mapping[str, Any]) -> str:
    case_key = str(record.get("case_key") or build_case_key(record))
    variant = str(record.get("forecast_variant_id") or "champion")
    return f"{case_key}:variant:{hashlib.sha256(variant.encode()).hexdigest()[:20]}"


def is_gold_actual(record: Mapping[str, Any]) -> bool:
    if record.get("verification_state") != "final" or record.get("match_class") not in GOLD_MATCH_CLASSES:
        return False
    if record.get("match_class") == "lineage_confirmed":
        return bool(record.get("lineage_evidence_type") and record.get("lineage_evidence_source") and record.get("lineage_evidence_timestamp") and record.get("lineage_evidence_ids"))
    return True


class VerificationStore:
    def __init__(self, path: str | os.PathLike[str] = "train_data/evaluation/forecast_verification.sqlite"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=FULL")
        return con

    def _init_schema(self):
        with self._connect() as con:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS forecast_cases(case_key TEXT PRIMARY KEY, payload_json TEXT NOT NULL, created_at_utc TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS forecast_variants(variant_key TEXT PRIMARY KEY, case_key TEXT NOT NULL REFERENCES forecast_cases(case_key), forecast_variant_id TEXT NOT NULL, payload_json TEXT NOT NULL, UNIQUE(case_key, forecast_variant_id));
            CREATE TABLE IF NOT EXISTS verification_revisions(revision_id INTEGER PRIMARY KEY AUTOINCREMENT, case_key TEXT NOT NULL REFERENCES forecast_cases(case_key), verification_state TEXT NOT NULL CHECK(verification_state IN ('pending','provisional','final','superseded','invalid')), match_class TEXT NOT NULL, supersedes_revision_id INTEGER REFERENCES verification_revisions(revision_id), idempotency_key TEXT NOT NULL UNIQUE, payload_json TEXT NOT NULL, generated_at_utc TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS final_actuals(case_key TEXT PRIMARY KEY REFERENCES forecast_cases(case_key), revision_id INTEGER NOT NULL UNIQUE REFERENCES verification_revisions(revision_id), payload_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS experiment_pairs(pair_id INTEGER PRIMARY KEY AUTOINCREMENT, case_key TEXT NOT NULL REFERENCES forecast_cases(case_key), champion_variant_key TEXT NOT NULL, challenger_variant_key TEXT NOT NULL, payload_json TEXT NOT NULL, UNIQUE(case_key, champion_variant_key, challenger_variant_key));
            CREATE INDEX IF NOT EXISTS idx_revisions_case ON verification_revisions(case_key, revision_id);
            """)

    def record(self, record: Mapping[str, Any]) -> dict:
        rec = dict(record)
        state = str(rec.get("verification_state") or "pending")
        match_class = str(rec.get("match_class") or "no_match")
        if state not in STATES or match_class not in MATCH_CLASSES:
            raise ValueError(f"invalid verification state/match class: {state}/{match_class}")
        if match_class == "lineage_confirmed" and not is_gold_actual({**rec, "verification_state": "final"}):
            state = "invalid"
        case_key = rec["case_key"] = str(rec.get("case_key") or build_case_key(rec))
        variant_key = rec["variant_key"] = str(rec.get("variant_key") or build_variant_key(rec))
        rec.setdefault("schema", SCHEMA)
        rec.setdefault("generated_at_utc", datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"))
        rec.setdefault("verification_config_hash", "unknown")
        rec.setdefault("matcher_contract_hash", hashlib.sha256("p105-gold-v1".encode()).hexdigest())
        identity = {k: rec.get(k) for k in CASE_FIELDS}
        fingerprint = {k: v for k, v in rec.items() if k not in {"generated_at_utc", "revision_id", "supersedes_revision_id", "verification_state"}}
        idem = hashlib.sha256((case_key + "\0" + state + "\0" + json.dumps(fingerprint, sort_keys=True, default=str)).encode()).hexdigest()
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            con.execute("INSERT OR IGNORE INTO forecast_cases VALUES(?,?,?)", (case_key, json.dumps(identity, ensure_ascii=False), rec["generated_at_utc"]))
            variant_id = str(rec.get("forecast_variant_id") or "champion")
            con.execute("INSERT OR IGNORE INTO forecast_variants VALUES(?,?,?,?)", (variant_key, case_key, variant_id, json.dumps({"forecast_variant_id": variant_id})))
            existing = con.execute("SELECT revision_id,payload_json FROM verification_revisions WHERE idempotency_key=?", (idem,)).fetchone()
            if existing:
                return json.loads(existing["payload_json"])
            active = con.execute("SELECT revision_id,verification_state,payload_json FROM verification_revisions WHERE case_key=? AND verification_state IN ('provisional','final') ORDER BY revision_id DESC LIMIT 1", (case_key,)).fetchone()
            # A weaker or diagnostic rerun is audit evidence, but can never
            # displace an established Actual.
            preserve_active = bool(active and (state in ("pending", "invalid") or (active["verification_state"] == "final" and state == "provisional")))
            if preserve_active:
                state = "superseded"
            supersedes = active["revision_id"] if active and state in ("provisional", "final") else None
            if supersedes:
                con.execute("DELETE FROM final_actuals WHERE case_key=?", (case_key,))
            rec["verification_state"] = state; rec["supersedes_revision_id"] = supersedes
            cur = con.execute("INSERT INTO verification_revisions(case_key,verification_state,match_class,supersedes_revision_id,idempotency_key,payload_json,generated_at_utc) VALUES(?,?,?,?,?,?,?)", (case_key,state,match_class,supersedes,idem,"{}",rec["generated_at_utc"]))
            rec["revision_id"] = cur.lastrowid
            payload = json.dumps(rec, ensure_ascii=False, sort_keys=True)
            con.execute("UPDATE verification_revisions SET payload_json=? WHERE revision_id=?", (payload, cur.lastrowid))
            if is_gold_actual(rec):
                con.execute("INSERT INTO final_actuals VALUES(?,?,?)", (case_key,cur.lastrowid,payload))
            return rec

    def latest(self) -> list[dict]:
        with self._connect() as con:
            rows = con.execute("""SELECT payload_json FROM verification_revisions r
                WHERE revision_id=COALESCE(
                  (SELECT MAX(revision_id) FROM verification_revisions x WHERE x.case_key=r.case_key AND x.verification_state IN ('final','provisional')),
                  (SELECT MAX(revision_id) FROM verification_revisions y WHERE y.case_key=r.case_key))
                ORDER BY case_key""").fetchall()
        return [json.loads(r[0]) for r in rows]

    def revisions(self) -> list[dict]:
        with self._connect() as con:
            rows = con.execute("SELECT payload_json FROM verification_revisions ORDER BY revision_id").fetchall()
            superseded = {r[0] for r in con.execute("SELECT supersedes_revision_id FROM verification_revisions WHERE supersedes_revision_id IS NOT NULL")}
        result=[]
        for row in rows:
            item=json.loads(row[0])
            if item.get("revision_id") in superseded:
                item["original_verification_state"]=item.get("verification_state")
                item["verification_state"]="superseded"
            result.append(item)
        return result

    def export_json_views(self, directory: str | os.PathLike[str] | None = None):
        out = Path(directory) if directory else self.path.parent
        out.mkdir(parents=True, exist_ok=True)
        for name, rows in (("forecast_verification_latest.jsonl", self.latest()), ("forecast_verification_revisions.jsonl", self.revisions())):
            fd, tmp = tempfile.mkstemp(prefix=f".{name}.", dir=out, text=True)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    for row in rows: fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                    fh.flush(); os.fsync(fh.fileno())
                os.replace(tmp, out / name)
            finally:
                if os.path.exists(tmp): os.unlink(tmp)
