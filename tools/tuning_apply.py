#!/usr/bin/env python3
"""P97 — Autonomes Tuning: Apply/Verify/Rollback.

Wird NICHT von der KI-Analyse direkt aufgerufen, sondern vom Dispatcher
nach dem Analyse-Lauf:

    python3 tools/tuning_apply.py --apply   # Nacht 1: Vorschlaege anwenden
    python3 tools/tuning_apply.py --verify  # Nacht 2: Ergebnis pruefen

Kill-Switch: AUTONOMOUS_TUNING_ENABLED muss True sein (default False).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import os
import tempfile
import fcntl
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ─── Projektverzeichnis ──────────────────────────────────────────────
REPO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_DIR))

import config  # noqa: E402
import runtime_config  # noqa: E402
from experiment_contract import (EXPERIMENT_SCHEMA, evaluate_paired_cases,
                                 stable_hash, validate_tuning_proposals)  # noqa: E402

# ─── Pfade ────────────────────────────────────────────────────────────
EVAL_DIR = REPO_DIR / "train_data" / "evaluation"
STATE_FILE = EVAL_DIR / "tuning_state.json"
HISTORY_FILE = EVAL_DIR / "tuning_history.jsonl"
RESULT_FILE = EVAL_DIR / "analysis_result.json"
DRIFT_FILE = EVAL_DIR / "drift_status.json"
STATUS_FILE = EVAL_DIR / "local_analysis_status.json"  # B488: Freshness-Pruefung
EXPERIMENTS_DIR = EVAL_DIR / "experiments"
LOCK_FILE = EVAL_DIR / ".tuning.lock"
# Nur Kompatibilitätsname für externe Diagnosewerkzeuge; Verify konsumiert ihn nie.
EXPERIMENT_RESULT_FILE = EVAL_DIR / "paired_experiment_result.json"


PLATEAU_ESCALATION_THRESHOLD = 3   # P103: nach so vielen Plateaus in Folge stoppen
STALL_ALARM_DAYS = 14              # P103: ohne akzeptierte Verbesserung seit so vielen Tagen


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _last_accepted_ts() -> str | None:
    """P103: Zeitstempel der letzten wirklich akzeptierten (echten) Verbesserung
    aus der Tuning-Historie, oder None falls es nie eine gab."""
    if not HISTORY_FILE.exists():
        return None
    last = None
    try:
        for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except Exception:
                continue
            if entry.get("action") == "accepted":
                last = entry.get("ts") or last
    except Exception:
        return None
    return last


def _first_history_ts() -> str | None:
    """P103: Referenzpunkt fuer den Stall-Alarm, falls es noch NIE eine
    akzeptierte Verbesserung gab — das Beobachtungsfenster beginnt dann mit dem
    ersten je aufgezeichneten Tuning-Ereignis, nicht erst mit einer (fehlenden)
    Verbesserung."""
    if not HISTORY_FILE.exists():
        return None
    try:
        lines = HISTORY_FILE.read_text(encoding="utf-8").splitlines()
        for line in lines:
            try:
                return json.loads(line).get("ts")
            except Exception:
                continue
    except Exception:
        return None
    return None


def _check_stall(state: dict) -> bool:
    """P103: Setzt/loescht state['quality_improvement_stalled'] und protokolliert
    einmalig einen stall_alarm-Eintrag, wenn seit STALL_ALARM_DAYS Tagen keine
    akzeptierte Verbesserung stattfand. Mutiert state in-place, schreibt selbst
    nicht auf Platte (Aufrufer ist dafuer verantwortlich)."""
    ref_ts = _last_accepted_ts() or _first_history_ts()
    if not ref_ts:
        return False
    try:
        ref_dt = datetime.strptime(ref_ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except Exception:
        return False
    stalled = (datetime.now(timezone.utc) - ref_dt).days >= STALL_ALARM_DAYS
    if stalled and not state.get("quality_improvement_stalled"):
        state["quality_improvement_stalled"] = True
        _append_history({"ts": _now_iso(), "action": "stall_alarm",
                         "reason": f"keine akzeptierte Verbesserung seit >= {STALL_ALARM_DAYS} Tagen"})
    elif not stalled:
        state.pop("quality_improvement_stalled", None)
    return stalled


def _log(msg: str) -> None:
    print(f"[TUNING] {msg}", file=sys.stderr)


def _append_history(entry: dict) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _current_mae_by_horizon() -> dict:
    ds = _read_json(DRIFT_FILE)
    if not ds:
        return {}
    qt = ds.get("quality_target_by_horizon", {})
    result = {}
    for horizon, value in qt.items():
        raw = value.get("actual_mae_km") if isinstance(value, dict) else None
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return {}
        number = float(raw)
        if not math.isfinite(number):
            return {}
        result[str(horizon)] = number
    return result


def _whitelist() -> dict:
    return getattr(config, "AUTONOMOUS_TUNING_PARAMS", {})


def _enabled() -> bool:
    rt = runtime_config.get("AUTONOMOUS_TUNING_ENABLED", None)
    if rt is not None:
        return bool(rt)
    return bool(getattr(config, "AUTONOMOUS_TUNING_ENABLED", False))


def _experiments_enabled() -> bool:
    return bool(runtime_config.get("FORECAST_EXPERIMENTS_ENABLED",
                                   getattr(config, "FORECAST_EXPERIMENTS_ENABLED", False)))


def _verification_config_hash() -> str:
    names = sorted(name for name in dir(config) if name.startswith(("VERIFICATION_", "LINEAGE_")))
    contract = {name: runtime_config.get(name, getattr(config, name, None)) for name in names}
    contract["matcher_code_hash"] = stable_hash((REPO_DIR / "accuracy_tracker.py").read_text(encoding="utf-8"))
    contract["schema"] = "verification-contract.v2"
    return stable_hash(contract)


def validate_proposal(name: str, value: float) -> str | None:
    """Prueft einen Vorschlag gegen die Whitelist. None = ok, sonst Fehlertext."""
    wl = _whitelist()
    if name not in wl:
        return f"{name} nicht in AUTONOMOUS_TUNING_PARAMS"
    spec = wl[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return f"{name}: Wert {value!r} ist nicht numerisch"
    if value < spec["min"] or value > spec["max"]:
        return f"{name}: {value} ausserhalb [{spec['min']}, {spec['max']}]"
    offset = round((value - spec["min"]) / spec["step"], 6)
    if abs(offset - round(offset)) > 0.01:
        return f"{name}: {value} ist kein Vielfaches von step={spec['step']} ab min={spec['min']}"
    return None


def _actuator_error(proposal: dict) -> str | None:
    name = proposal["parameter"]
    spec = _whitelist().get(name, {})
    if spec.get("target_system") != proposal["target_system"]:
        return "parameter_does_not_affect_target_system"
    if abs(float(proposal["new_value"]) - float(proposal["old_value"])) > float(
            spec.get("max_change_per_experiment", spec["step"])) + 1e-12:
        return "candidate_change_exceeds_maximum_step"
    for requirement, expected in spec.get("requires", {}).items():
        if runtime_config.get(requirement, getattr(config, requirement, None)) != expected:
            return "actuator_not_effective"
    return None


def _cmd_apply_unlocked() -> int:
    """Erzeugt ausschliesslich eine Shadow-Candidate-Konfiguration."""
    if not _enabled() or not _experiments_enabled():
        _log("Autonomes Tuning oder Forecast-Experimente sind deaktiviert.")
        return 0
    status = _read_json(STATUS_FILE)
    result = _read_json(RESULT_FILE)
    state = _read_json(STATE_FILE) or {"baselines": {}, "pending": {}}
    if not status or status.get("state") != "ok" or not result:
        _log("Kein erfolgreicher aktueller Analyse-Lauf — kein Apply.")
        return 0
    for field in ("analysis_run_id", "source_snapshot_id", "git_commit", "result_id"):
        if not status.get(field) or status.get(field) != result.get(field):
            _log(f"Laufbindung stimmt nicht: {field}")
            return 0
    try:
        generated = datetime.fromisoformat(result["generated_at_utc"].replace("Z", "+00:00"))
        started = datetime.fromisoformat(status["run_started_at_utc"].replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        _log("Laufzeitstempel fehlen oder sind ungültig.")
        return 0
    if generated < started or state.get("last_consumed_result_id") == result["result_id"]:
        _log("Ergebnis ist veraltet oder bereits konsumiert.")
        return 0
    if state.get("pending") or state.get("escalation_needed"):
        _log("Pending-Experiment oder Eskalationssperre aktiv.")
        return 0
    try:
        proposals = validate_tuning_proposals(
            result, _whitelist(),
            lambda name: runtime_config.get(name, getattr(config, name)),
            set(getattr(config, "ML_FORECAST_HORIZONS_MIN", [10, 20, 30, 40, 60])),
        )
    except (ValueError, TypeError, AttributeError) as exc:
        _append_history({"ts": _now_iso(), "action": "invalid_experiment", "reason": str(exc),
                         "result_id": result.get("result_id")})
        _log(f"Proposal abgelehnt: {exc}")
        return 0
    if not proposals:
        _log("Kein Tuning-Vorschlag.")
        return 0
    proposal = proposals[0]
    actuator_error = _actuator_error(proposal)
    if actuator_error:
        _append_history({"ts": _now_iso(), "action": "invalid_experiment", "reason": actuator_error,
                         "experiment_id": proposal["experiment_id"]})
        return 0
    name = proposal["parameter"]
    incumbent = {key: runtime_config.get(key, getattr(config, key)) for key in _whitelist()}
    candidate = dict(incumbent); candidate[name] = proposal["new_value"]
    policy = dict(config.FORECAST_EXPERIMENT_POLICY)
    policy_hash = stable_hash(policy)
    now = datetime.now(timezone.utc)
    minimum_hours = max(int(config.FORECAST_EXPERIMENT_MIN_RUNTIME_HOURS), 0)
    maximum_hours = min(int(proposal["maximum_runtime_hours"]),
                        int(config.FORECAST_EXPERIMENT_MAX_RUNTIME_HOURS))
    effective_samples = {str(h): max(int(proposal["minimum_paired_samples"][str(h)]),
                                     int(config.FORECAST_EXPERIMENT_MIN_PAIRED_SAMPLES_PER_HORIZON))
                         for h in proposal["target_horizons"]}
    experiment_dir = EXPERIMENTS_DIR / proposal["experiment_id"]
    incumbent_variant = f"{proposal['target_system']}_incumbent:{proposal['experiment_id']}"
    candidate_variant = f"{proposal['target_system']}_candidate:{proposal['experiment_id']}"
    manifest = {
        "schema": EXPERIMENT_SCHEMA, "experiment_id": proposal["experiment_id"],
        "analysis_run_id": result["analysis_run_id"], "result_id": result["result_id"],
        "source_snapshot_id": result["source_snapshot_id"], "git_commit": result["git_commit"],
        "target_system": proposal["target_system"], "target_horizons": proposal["target_horizons"],
        "parameter": name, "incumbent_value": proposal["old_value"], "candidate_value": proposal["new_value"],
        "incumbent_parameter_set": incumbent, "candidate_parameter_set": candidate,
        "incumbent_parameter_set_hash": stable_hash(incumbent), "candidate_parameter_set_hash": stable_hash(candidate),
        "forecast_variant_id_incumbent": incumbent_variant, "forecast_variant_id_candidate": candidate_variant,
        "policy": policy, "policy_hash": policy_hash, "verification_config_hash": _verification_config_hash(),
        "matcher_contract_hash": _verification_config_hash(),
        "forecast_code_hash": stable_hash((REPO_DIR / "prediction.py").read_text(encoding="utf-8")),
        "minimum_runtime_hours": minimum_hours, "maximum_runtime_hours": maximum_hours,
        "not_before_utc": (now + timedelta(hours=minimum_hours)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at_utc": (now + timedelta(hours=maximum_hours)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "created_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _atomic_json(experiment_dir / "manifest.json", manifest)
    _atomic_json(experiment_dir / "status.json", {"experiment_id": proposal["experiment_id"], "state": "collecting"})
    state.update({
        "schema": "wetterextended.tuning-state.v2",
        "analysis_run_id": result["analysis_run_id"], "source_snapshot_id": result["source_snapshot_id"],
        "git_commit": result["git_commit"], "last_consumed_result_id": result["result_id"],
        "last_consumed_analysis_run_id": result["analysis_run_id"],
        "pending": {"experiment_id": proposal["experiment_id"], "state": "shadow_collecting",
                    "target_system": proposal["target_system"], "target_horizons": proposal["target_horizons"],
                    "parameter": name, "incumbent_value": proposal["old_value"],
                    "candidate_value": proposal["new_value"], "candidate_parameter_set": candidate,
                    "parameter_set_hash": stable_hash(candidate), "policy_hash": policy_hash,
                    "verification_config_hash": manifest["verification_config_hash"],
                    "forecast_variant_id": candidate_variant,
                    "minimum_paired_samples": effective_samples,
                    "minimum_runtime_hours": minimum_hours, "maximum_runtime_hours": maximum_hours,
                    "started_at_utc": manifest["created_at_utc"], "not_before_utc": manifest["not_before_utc"],
                    "expires_at_utc": manifest["expires_at_utc"]},
    })
    _atomic_json(STATE_FILE, state)
    _append_history({"ts": _now_iso(), "action": "shadow_candidate_created",
                     "experiment_id": proposal["experiment_id"], "param": name,
                     "old": proposal["old_value"], "new": proposal["new_value"],
                     "result_id": result["result_id"]})
    _log("Shadow-Candidate erzeugt; produktive Runtime-Konfiguration unverändert.")
    return 0

def _cmd_verify_unlocked() -> int:
    """Entscheidet ausschliesslich anhand gepaarter finaler Shadow-Fälle."""
    if not _enabled() or not _experiments_enabled():
        _log("Autonomes Tuning oder Forecast-Experimente sind deaktiviert.")
        return 0
    state = _read_json(STATE_FILE) or {}
    pending = state.get("pending")
    if not isinstance(pending, dict) or not pending.get("experiment_id"):
        _log("Kein pending Shadow-Experiment.")
        return 0
    manifest = _read_json(EXPERIMENTS_DIR / pending["experiment_id"] / "manifest.json")
    result = _read_json(EXPERIMENTS_DIR / pending["experiment_id"] / "result.json")
    if not result or result.get("schema") != EXPERIMENT_SCHEMA:
        _log("Kein gepaartes Experimentergebnis; Candidate bleibt im Shadow.")
        return 0
    if result.get("experiment_id") != pending["experiment_id"]:
        _log("Experiment-ID des Ergebnisses stimmt nicht.")
        return 0
    if not manifest or any(result.get(field) != manifest.get(field) for field in (
            "experiment_id", "analysis_run_id", "source_snapshot_id", "git_commit", "policy_hash",
            "verification_config_hash", "matcher_contract_hash", "forecast_code_hash")):
        return _finish_experiment(state, "invalid_experiment", result, "manifest_binding_changed")
    now = datetime.now(timezone.utc)
    expires = datetime.fromisoformat(manifest["expires_at_utc"].replace("Z", "+00:00"))
    not_before = datetime.fromisoformat(manifest["not_before_utc"].replace("Z", "+00:00"))
    if now >= expires:
        return _finish_experiment(state, "insufficient_samples_expired", result, "experiment_expired")
    if now < not_before:
        pending["state"] = "collecting"
        _atomic_json(STATE_FILE, state)
        return 0
    if result.get("verification_config_hash") != pending.get("verification_config_hash"):
        return _finish_experiment(state, "invalid_experiment", result, "verification_config_changed")
    cases = result.get("paired_cases")
    if not isinstance(cases, list):
        return _finish_experiment(state, "invalid_measurement", result, "paired_cases_missing")
    coverage = {key: result.get(key, 0) for key in ("eligible_case_count", "candidate_missing_count",
                                                     "candidate_rejected_count", "candidate_fallback_count")}
    decision = evaluate_paired_cases(cases, pending["minimum_paired_samples"], policy=manifest["policy"],
                                     target_horizons=manifest["target_horizons"],
                                     manifest={**manifest, **coverage})
    outcome = decision["state"]
    if outcome != "improved":
        return _finish_experiment(state, outcome, decision, "acceptance_criteria_not_met")
    # Erst jetzt atomare Promotion des genau einen Parameters.
    before = runtime_config.get(pending["parameter"], getattr(config, pending["parameter"]))
    intent = EXPERIMENTS_DIR / pending["experiment_id"] / "promotion_intent.json"
    _atomic_json(intent, {"state": "intent", "parameter": pending["parameter"], "before": before,
                          "candidate": pending["candidate_value"], "created_at_utc": _now_iso()})
    patched = False
    try:
        runtime_config.patch({pending["parameter"]: pending["candidate_value"]}); patched = True
        effective = runtime_config.get(pending["parameter"], getattr(config, pending["parameter"]))
        if not math.isclose(float(effective), float(pending["candidate_value"]), abs_tol=1e-12):
            raise RuntimeError("runtime_value_verification_failed")
        state.setdefault("baselines", {})[pending["parameter"]] = pending["candidate_value"]
        state["last_improvement_at_utc"] = _now_iso(); state["plateau_streak"] = 0
        state.pop("escalation_needed", None)
        rc = _finish_experiment(state, "improved", decision, "statistically_significant_improvement")
        _atomic_json(intent, {"state": "committed", "before": before, "effective": effective})
        return rc
    except Exception as exc:
        rollback_ok = False
        if patched:
            try:
                runtime_config.patch({pending["parameter"]: before})
                rollback_ok = math.isclose(float(runtime_config.get(pending["parameter"], before)), float(before), abs_tol=1e-12)
            except Exception:
                rollback_ok = False
        _atomic_json(intent, {"state": "rolled_back" if rollback_ok else "rollback_failed",
                              "before": before, "error": str(exc)})
        _append_history({"ts": _now_iso(), "action": "promotion_failed", "error": str(exc),
                         "rollback_ok": rollback_ok, "experiment_id": pending["experiment_id"]})
        return 1


def _finish_experiment(state: dict, outcome: str, result: dict, reason: str) -> int:
    pending = state.get("pending", {})
    if outcome == "plateau":
        state["plateau_streak"] = int(state.get("plateau_streak", 0)) + 1
        if state["plateau_streak"] >= PLATEAU_ESCALATION_THRESHOLD:
            state["escalation_needed"] = True
    elif outcome not in ("insufficient_samples", "insufficient_samples_collecting"):
        state["plateau_streak"] = 0
    if outcome not in ("insufficient_samples", "insufficient_samples_collecting"):
        state["pending"] = {}
    state["last_experiment_result"] = {"experiment_id": pending.get("experiment_id"),
                                       "state": outcome, "reason": reason, **result}
    _atomic_json(STATE_FILE, state)
    _append_history({"ts": _now_iso(), "action": outcome, "reason": reason,
                     "experiment_id": pending.get("experiment_id"), "metrics": result})
    return 0


def _run_locked(callback) -> int:
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_FILE, "a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return callback()


def cmd_apply() -> int:
    return _run_locked(_cmd_apply_unlocked)


def cmd_verify() -> int:
    return _run_locked(_cmd_verify_unlocked)

def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description="P97 — Autonomes Tuning Apply/Verify")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--apply", action="store_true", help="Vorschlaege anwenden (Nacht 1)")
    group.add_argument("--verify", action="store_true", help="Ergebnis pruefen (Nacht 2)")
    args = parser.parse_args(argv)
    if args.apply:
        return cmd_apply()
    return cmd_verify()


if __name__ == "__main__":
    sys.exit(main())
