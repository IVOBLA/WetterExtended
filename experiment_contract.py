"""Versionierte, deterministische Verträge für sichere Forecast-Experimente."""
from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
import uuid
from datetime import datetime, timezone

LOCAL_ANALYSIS_SCHEMA = "wetterextended.local-analysis.v2"
EXPERIMENT_SCHEMA = "wetterextended.forecast-experiment.v1"
PROPOSAL_FIELDS = frozenset({
    "experiment_id", "target_system", "target_horizons", "parameter",
    "old_value", "new_value", "code_ref", "evidence_refs", "expected_effect",
    "minimum_paired_samples", "maximum_runtime_hours",
})
TARGET_SYSTEMS = frozenset({"kinematic", "ml", "routing_gate"})


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stable_hash(value) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def new_id() -> str:
    return str(uuid.uuid4())


def _number(value, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field} muss eine endliche Zahl (kein Boolean) sein")
    return float(value)


def validate_tuning_proposals(payload: dict, whitelist: dict, current_value,
                              valid_horizons: set[int]) -> list[dict]:
    """Validiert ausschließlich strukturierte Daten; Freitext wird nie aktuiert."""
    if payload.get("schema") != LOCAL_ANALYSIS_SCHEMA:
        raise ValueError("unbekannte oder fehlende Analyse-Schema-Version")
    for field in ("analysis_run_id", "source_snapshot_id", "git_commit", "result_id",
                  "generated_at_utc"):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            raise ValueError(f"{field} fehlt")
    proposals = payload.get("tuning_proposals", [])
    if not isinstance(proposals, list) or len(proposals) > 1:
        raise ValueError("tuning_proposals muss eine Liste mit maximal einem Experiment sein")
    for proposal in proposals:
        if not isinstance(proposal, dict):
            raise ValueError("Proposal muss ein Objekt sein")
        unknown = set(proposal) - PROPOSAL_FIELDS
        missing = PROPOSAL_FIELDS - set(proposal)
        if unknown or missing:
            raise ValueError(f"Proposal-Felder ungültig; unbekannt={sorted(unknown)}, fehlend={sorted(missing)}")
        try:
            uuid.UUID(proposal["experiment_id"])
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("experiment_id ist keine UUID") from exc
        if proposal["target_system"] not in TARGET_SYSTEMS:
            raise ValueError("target_system ist ungültig")
        name = proposal["parameter"]
        if name not in whitelist:
            raise ValueError(f"{name} ist nicht autonom freigegeben")
        old = _number(proposal["old_value"], "old_value")
        new = _number(proposal["new_value"], "new_value")
        actual = _number(current_value(name), "runtime_value")
        if not math.isclose(old, actual, rel_tol=0, abs_tol=1e-12):
            raise ValueError(f"old_value stimmt nicht mit Runtime-Konfiguration für {name} überein")
        spec = whitelist[name]
        if not spec["min"] <= new <= spec["max"]:
            raise ValueError(f"new_value für {name} liegt außerhalb der Bounds")
        steps = (new - spec["min"]) / spec["step"]
        if not math.isclose(steps, round(steps), abs_tol=1e-9):
            raise ValueError(f"new_value für {name} verletzt step")
        if math.isclose(old, new, rel_tol=0, abs_tol=1e-12):
            raise ValueError("Candidate unterscheidet sich nicht vom Incumbent")
        horizons = proposal["target_horizons"]
        if not isinstance(horizons, list) or not horizons or any(
                isinstance(h, bool) or not isinstance(h, int) or h not in valid_horizons for h in horizons):
            raise ValueError("target_horizons sind ungültig")
        mins = proposal["minimum_paired_samples"]
        if not isinstance(mins, dict) or set(mins) != {str(h) for h in horizons} or any(
                isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in mins.values()):
            raise ValueError("minimum_paired_samples muss jeden Zielhorizont positiv abdecken")
        if not isinstance(proposal["code_ref"], str) or not proposal["code_ref"].strip():
            raise ValueError("code_ref fehlt")
        if not isinstance(proposal["evidence_refs"], list) or not proposal["evidence_refs"]:
            raise ValueError("evidence_refs fehlen")
        if not isinstance(proposal["expected_effect"], str) or not proposal["expected_effect"].strip():
            raise ValueError("expected_effect fehlt")
        hours = _number(proposal["maximum_runtime_hours"], "maximum_runtime_hours")
        if hours <= 0 or hours > 168:
            raise ValueError("maximum_runtime_hours liegt außerhalb (0, 168]")
    return proposals


def evaluate_paired_cases(cases: list[dict], minimum_samples: dict[str, int],
                          *, bootstrap_iterations: int = 2000) -> dict:
    """Block-Bootstrap nach event_id; akzeptiert weder Plateau noch Regression."""
    required = {"case_key", "horizon_min", "event_id", "cell_id",
                "incumbent_error_km", "candidate_error_km"}
    if not cases or any(not required <= set(c) for c in cases):
        return {"state": "invalid_measurement"}
    for c in cases:
        try:
            _number(c["incumbent_error_km"], "incumbent_error_km")
            _number(c["candidate_error_km"], "candidate_error_km")
        except ValueError:
            return {"state": "invalid_measurement"}
    by_horizon = {}
    for c in cases:
        by_horizon.setdefault(str(c["horizon_min"]), []).append(c)
    if any(len(by_horizon.get(h, [])) < n for h, n in minimum_samples.items()):
        return {"state": "insufficient_samples", "paired_samples": len(cases)}
    deltas = [c["candidate_error_km"] - c["incumbent_error_km"] for c in cases]
    blocks = {}
    for c, delta in zip(cases, deltas):
        blocks.setdefault(str(c["event_id"]), []).append(delta)
    rng = random.Random(stable_hash([c["case_key"] for c in cases]))
    block_values = list(blocks.values())
    boot = []
    for _ in range(bootstrap_iterations):
        draw = [rng.choice(block_values) for _ in block_values]
        boot.append(statistics.fmean(x for block in draw for x in block))
    ci_upper = sorted(boot)[max(0, math.ceil(.95 * len(boot)) - 1)]
    mean_delta = statistics.fmean(deltas)
    incumbent_mae = statistics.fmean(c["incumbent_error_km"] for c in cases)
    margin = max(.05, incumbent_mae * .02)
    horizon_metrics = {}
    regression = False
    for horizon, rows in by_horizon.items():
        inc = statistics.fmean(r["incumbent_error_km"] for r in rows)
        delta = statistics.fmean(r["candidate_error_km"] - r["incumbent_error_km"] for r in rows)
        guard = max(.03, inc * .01)
        regression |= delta > guard
        horizon_metrics[horizon] = {"paired_samples": len(rows), "incumbent_mae_km": inc,
                                    "mean_delta_km": delta, "regression_guard_km": guard}
    if regression or mean_delta > 0:
        state = "rejected"
    elif mean_delta >= -margin or ci_upper >= 0:
        state = "plateau"
    else:
        state = "improved"
    return {"schema": EXPERIMENT_SCHEMA, "state": state, "mean_delta_km": mean_delta,
            "median_delta_km": statistics.median(deltas), "ci95_upper_km": ci_upper,
            "paired_samples": len(cases), "unique_cells": len({c["cell_id"] for c in cases}),
            "unique_events": len(blocks), "minimum_improvement_km": margin,
            "by_horizon": horizon_metrics}
