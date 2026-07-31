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
EXPERIMENT_SCHEMA = "wetterextended.forecast-experiment.v2"
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
        if spec.get("target_system") != proposal["target_system"]:
            raise ValueError("Parameter ist einem anderen target_system zugeordnet")
        if not spec["min"] <= new <= spec["max"]:
            raise ValueError(f"new_value für {name} liegt außerhalb der Bounds")
        steps = (new - spec["min"]) / spec["step"]
        if not math.isclose(steps, round(steps), abs_tol=1e-9):
            raise ValueError(f"new_value für {name} verletzt step")
        if math.isclose(old, new, rel_tol=0, abs_tol=1e-12):
            raise ValueError("Candidate unterscheidet sich nicht vom Incumbent")
        if abs(new - old) > float(spec.get("max_change_per_experiment", spec["step"])) + 1e-12:
            raise ValueError("Candidate-Änderung überschreitet einen erlaubten Schritt")
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
                          *, policy: dict | None = None, target_horizons=None,
                          manifest: dict | None = None,
                          bootstrap_iterations: int | None = None) -> dict:
    """Block-Bootstrap nach event_id; akzeptiert weder Plateau noch Regression."""
    policy = dict(policy or {
        "min_absolute_improvement_km": .05, "min_relative_improvement": .02,
        "max_absolute_horizon_regression_km": .03,
        "max_relative_horizon_regression": .01, "bootstrap_iterations": 2000,
        "confidence_level": .95, "min_unique_cells": 1, "min_unique_events": 1,
        "hard_guards": ["coverage", "hit_rate", "direction_error", "speed_error"],
    })
    bootstrap_iterations = int(bootstrap_iterations or policy["bootstrap_iterations"])
    required = {"case_key", "horizon_min", "event_id", "cell_id",
                "incumbent_error_km", "candidate_error_km"}
    if not cases or any(not required <= set(c) for c in cases):
        return {"state": "invalid_measurement"}
    keys = [str(c.get("case_key")) for c in cases]
    if len(keys) != len(set(keys)):
        return {"state": "invalid_measurement", "reason": "duplicate_case_key"}
    allowed_horizons = {int(h) for h in (target_horizons or minimum_samples)}
    for c in cases:
        try:
            _number(c["incumbent_error_km"], "incumbent_error_km")
            _number(c["candidate_error_km"], "candidate_error_km")
        except ValueError:
            return {"state": "invalid_measurement"}
        if int(c["horizon_min"]) not in allowed_horizons:
            return {"state": "invalid_measurement", "reason": "non_target_horizon"}
        if manifest:
            if (c.get("state") != "final" or c.get("eligible_for_model_tuning") is not True
                    or c.get("match_type") not in {"exact_id", "exact_cell_id", "lineage_confirmed"}):
                return {"state": "invalid_measurement", "reason": "actual_not_gold_final"}
            for field in ("experiment_id", "policy_hash", "verification_config_hash",
                          "matcher_contract_hash"):
                if c.get(field) != manifest.get(field):
                    return {"state": "invalid_measurement", "reason": f"binding_mismatch:{field}"}
            if c.get("forecast_variant_id_incumbent") != manifest.get("forecast_variant_id_incumbent") or c.get(
                    "forecast_variant_id_candidate") != manifest.get("forecast_variant_id_candidate"):
                return {"state": "invalid_measurement", "reason": "variant_mismatch"}
            if (c.get("incumbent_actual_id") != c.get("candidate_actual_id") or
                    c.get("incumbent_actual_lat") != c.get("candidate_actual_lat") or
                    c.get("incumbent_actual_lon") != c.get("candidate_actual_lon")):
                return {"state": "invalid_measurement", "reason": "actual_mismatch"}
    by_horizon = {}
    for c in cases:
        by_horizon.setdefault(str(c["horizon_min"]), []).append(c)
    if any(len(by_horizon.get(h, [])) < n for h, n in minimum_samples.items()):
        return {"state": "insufficient_samples", "paired_samples": len(cases)}
    unique_cells = len({str(c["cell_id"]) for c in cases})
    unique_events = len({str(c["event_id"]) for c in cases})
    if unique_cells < int(policy["min_unique_cells"]) or unique_events < int(policy["min_unique_events"]):
        return {"state": "insufficient_samples", "paired_samples": len(cases),
                "unique_cells": unique_cells, "unique_events": unique_events}
    eligible = int((manifest or {}).get("eligible_case_count", len(cases)))
    missing = int((manifest or {}).get("candidate_missing_count", 0))
    rejected_count = int((manifest or {}).get("candidate_rejected_count", 0))
    fallback_count = int((manifest or {}).get("candidate_fallback_count", 0))
    if missing or rejected_count or len(cases) < eligible:
        return {"state": "rejected", "reason": "candidate_coverage_regression",
                "paired_samples": len(cases), "eligible_incumbent_cases": eligible}
    guard_failures = []
    for name in ("direction", "speed", "hit_rate"):
        if any(bool(c.get(f"{name}_regression")) for c in cases): guard_failures.append(name)
    if guard_failures:
        return {"state": "rejected", "reason": "hard_guard_regression", "hard_guard_failures": guard_failures,
                "paired_samples": len(cases), "unique_cells": unique_cells, "unique_events": unique_events}
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
    confidence = float(policy["confidence_level"])
    ci_upper = sorted(boot)[max(0, math.ceil(confidence * len(boot)) - 1)]
    mean_delta = statistics.fmean(deltas)
    incumbent_mae = statistics.fmean(c["incumbent_error_km"] for c in cases)
    margin = max(float(policy["min_absolute_improvement_km"]),
                 incumbent_mae * float(policy["min_relative_improvement"]))
    horizon_metrics = {}
    regression = False
    for horizon, rows in by_horizon.items():
        inc = statistics.fmean(r["incumbent_error_km"] for r in rows)
        delta = statistics.fmean(r["candidate_error_km"] - r["incumbent_error_km"] for r in rows)
        guard = max(float(policy["max_absolute_horizon_regression_km"]),
                    inc * float(policy["max_relative_horizon_regression"]))
        regression |= delta > guard
        candidate_mae = statistics.fmean(r["candidate_error_km"] for r in rows)
        horizon_metrics[horizon] = {"paired_samples": len(rows), "incumbent_mae_km": inc,
                                    "candidate_mae_km": candidate_mae,
                                    "mean_delta_km": delta, "regression_guard_km": guard,
                                    "unique_cells": len({r["cell_id"] for r in rows}),
                                    "unique_events": len({r["event_id"] for r in rows})}
    if regression or mean_delta > 0:
        state = "rejected"
    elif mean_delta >= -margin or ci_upper >= 0:
        state = "plateau"
    else:
        state = "improved"
    return {"schema": EXPERIMENT_SCHEMA, "state": state, "mean_delta_km": mean_delta,
            "median_delta_km": statistics.median(deltas), "ci95_upper_km": ci_upper,
            "paired_samples": len(cases), "unique_cells": unique_cells,
            "unique_events": unique_events, "minimum_improvement_km": margin,
            "candidate_coverage_rate": len(cases) / eligible if eligible else 0.0,
            "incumbent_coverage_rate": 1.0, "candidate_missing_rate": missing / eligible if eligible else 0.0,
            "candidate_reject_rate": rejected_count / eligible if eligible else 0.0,
            "candidate_fallback_rate": fallback_count / eligible if eligible else 0.0,
            "by_horizon": horizon_metrics}
