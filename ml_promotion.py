"""Kanonische, horizonspezifische ML-Promotion auf finalen Gold-Faellen."""
from __future__ import annotations

import json
from pathlib import Path

from experiment_contract import evaluate_paired_cases, stable_hash, utc_now
from quality_contract import atomic_write_json, provenance

MANIFEST_SCHEMA = "wetterextended.active-forecast-models.v1"


def _sample_set(rows):
    return stable_hash([{"case_key": r["case_key"], "verification_config_hash": r.get("verification_config_hash"),
                         "matcher_contract_hash": r.get("matcher_contract_hash")} for r in sorted(rows, key=lambda x: x["case_key"])])


def evaluate_ml_candidate(gold_cases: list[dict], *, candidate_version: str,
                          active_version: str | None, family="lgbm", policy=None,
                          minimum_samples=None) -> dict:
    """Vergleicht Candidate, aktives ML und Kinematik ausschliesslich zeilengleich.

    Jede Eingabezeile muss die drei Fehler enthalten. Fehlende Predictions gelten
    als Coverage-Regression und koennen nie durch Pairwise-Dropping verschwinden.
    """
    minimum_samples = minimum_samples or {}
    required = {"case_key", "horizon_min", "event_id", "cell_id", "candidate_error_km", "kinematic_error_km"}
    eligible = [r for r in gold_cases if r.get("verification_state", r.get("state")) == "final"
                and r.get("eligible_for_model_tuning") is True
                and r.get("match_class", r.get("match_type")) in {"exact_id", "exact_cell_id", "lineage_confirmed"}]
    horizons = sorted({int(r["horizon_min"]) for r in eligible if required <= set(r)})
    by_horizon, decisions = {}, {}
    for horizon in horizons:
        source = [r for r in eligible if int(r["horizon_min"]) == horizon]
        complete = [r for r in source if required <= set(r) and (active_version is None or "active_ml_error_km" in r)]
        sample_id = _sample_set(complete)
        common = {"sample_set_id": sample_id, "case_keys": [r["case_key"] for r in complete]}
        def compare(baseline):
            cases = [{"case_key": r["case_key"], "horizon_min": horizon, "event_id": r["event_id"], "cell_id": r["cell_id"],
                      "incumbent_error_km": r[baseline], "candidate_error_km": r["candidate_error_km"],
                      **{k: r.get(k) for k in ("direction_error_delta", "speed_error_delta", "hit_rate_delta")}} for r in complete]
            outcome = evaluate_paired_cases(cases, {str(horizon): int(minimum_samples.get(str(horizon), minimum_samples.get(horizon, 1)))},
                                            policy=policy, target_horizons=[horizon])
            rejected = sum(bool(r.get("candidate_rejected")) for r in source)
            fallback = sum(bool(r.get("candidate_fallback")) for r in source)
            if len(complete) < len(source) or rejected or fallback:
                outcome.update({"state": "rejected", "reason": "candidate_coverage_regression",
                                "eligible_incumbent_cases": len(source)})
            outcome.update({"candidate_coverage_rate": len(complete) / len(source) if source else 0.0, **common})
            return outcome
        kin = compare("kinematic_error_km")
        incumbent = compare("active_ml_error_km") if active_version else None
        guards_ok = all(not bool(r.get("direction_regression") or r.get("speed_regression") or r.get("hit_rate_regression")) for r in complete)
        promoted = kin.get("state") == "improved" and (incumbent is None or incumbent.get("state") == "improved") and guards_ok
        state = "promoted" if promoted else ("plateau" if kin.get("state") == "plateau" or (incumbent and incumbent.get("state") == "plateau") else "rejected")
        reason = None if promoted else ("cold_start_shadow_until_kinematic_beaten" if active_version is None and kin.get("state") != "improved" else "rejected_not_better")
        by_horizon[str(horizon)] = {"candidate_vs_kinematic": kin, "candidate_vs_active_ml": incumbent,
                                    "sample_set_id": sample_id, "case_keys": common["case_keys"], "guards_ok": guards_ok,
                                    "state": state, "reason": reason}
        decisions[str(horizon)] = {"mode": "ml", "model_version": candidate_version, "family": family} if promoted else {
            "mode": "kinematic", "reason": reason or "policy_not_passed"}
    return {"schema": "wetterextended.ml-promotion.v1", "generated_at_utc": utc_now(), "candidate_version": candidate_version,
            "active_version": active_version, "family": family, "by_horizon": by_horizon,
            "active_manifest": {"schema": MANIFEST_SCHEMA, "generated_at_utc": utc_now(), "by_horizon": decisions}}


def write_active_manifest(path, evaluation: dict) -> dict:
    manifest = dict(evaluation["active_manifest"])
    manifest.update(provenance(generated_by="ml_promotion.write_active_manifest", records=list(manifest["by_horizon"].values())))
    manifest["schema"] = MANIFEST_SCHEMA
    atomic_write_json(path, manifest)
    return manifest


def load_active_manifest(path) -> dict:
    path = Path(path)
    if not path.exists(): return {"schema": MANIFEST_SCHEMA, "by_horizon": {}}
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema") != MANIFEST_SCHEMA: return {"schema": MANIFEST_SCHEMA, "by_horizon": {}, "legacy_incomparable": True}
    return value
