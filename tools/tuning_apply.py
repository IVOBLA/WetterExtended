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
from datetime import datetime, timezone
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
    names = ("VERIFICATION_NN_MAX_MATCH_KM", "VERIFICATION_TIME_TOLERANCE_S",
             "VERIFICATION_MAX_SEARCH_RADIUS_KM", "VERIFICATION_INTERPOLATION_MAX_GAP_S")
    return stable_hash({name: runtime_config.get(name, getattr(config, name, None)) for name in names})


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
    if proposal["target_system"] == "kinematic" and not name.startswith("KINEMATIC_"):
        return "parameter_does_not_affect_target_system"
    if proposal["target_system"] == "ml" and not (name.startswith("ML_") or name.startswith("FORECAST_")):
        return "parameter_does_not_affect_target_system"
    if name == "KINEMATIC_ACCEL_MAX_FRACTION" and not bool(runtime_config.get(
            "KINEMATIC_ACCELERATION_ENABLED", getattr(config, "KINEMATIC_ACCELERATION_ENABLED", False))):
        return "actuator_not_effective"
    return None


def cmd_apply() -> int:
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
    candidate = {name: proposal["new_value"]}
    state.update({
        "schema": "wetterextended.tuning-state.v2",
        "analysis_run_id": result["analysis_run_id"], "source_snapshot_id": result["source_snapshot_id"],
        "git_commit": result["git_commit"], "last_consumed_result_id": result["result_id"],
        "last_consumed_analysis_run_id": result["analysis_run_id"],
        "pending": {"experiment_id": proposal["experiment_id"], "state": "shadow_collecting",
                    "target_system": proposal["target_system"], "target_horizons": proposal["target_horizons"],
                    "parameter": name, "incumbent_value": proposal["old_value"],
                    "candidate_value": proposal["new_value"], "candidate_parameter_set": candidate,
                    "parameter_set_hash": stable_hash(candidate),
                    "verification_config_hash": _verification_config_hash(),
                    "forecast_variant_id": f"{proposal['target_system']}_candidate:{proposal['experiment_id']}",
                    "minimum_paired_samples": proposal["minimum_paired_samples"],
                    "started_at_utc": _now_iso()},
    })
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    _append_history({"ts": _now_iso(), "action": "shadow_candidate_created",
                     "experiment_id": proposal["experiment_id"], "param": name,
                     "old": proposal["old_value"], "new": proposal["new_value"],
                     "result_id": result["result_id"]})
    _log("Shadow-Candidate erzeugt; produktive Runtime-Konfiguration unverändert.")
    return 0

def cmd_verify() -> int:
    """Entscheidet ausschliesslich anhand gepaarter finaler Shadow-Fälle."""
    if not _enabled() or not _experiments_enabled():
        _log("Autonomes Tuning oder Forecast-Experimente sind deaktiviert.")
        return 0
    state = _read_json(STATE_FILE) or {}
    pending = state.get("pending")
    if not isinstance(pending, dict) or not pending.get("experiment_id"):
        _log("Kein pending Shadow-Experiment.")
        return 0
    result = _read_json(EXPERIMENT_RESULT_FILE)
    if not result or result.get("schema") != EXPERIMENT_SCHEMA:
        _log("Kein gepaartes Experimentergebnis; Candidate bleibt im Shadow.")
        return 0
    if result.get("experiment_id") != pending["experiment_id"]:
        _log("Experiment-ID des Ergebnisses stimmt nicht.")
        return 0
    if result.get("verification_config_hash") != pending.get("verification_config_hash"):
        return _finish_experiment(state, "invalid_experiment", result, "verification_config_changed")
    cases = result.get("paired_cases")
    if not isinstance(cases, list):
        return _finish_experiment(state, "invalid_measurement", result, "paired_cases_missing")
    decision = evaluate_paired_cases(cases, pending["minimum_paired_samples"])
    outcome = decision["state"]
    if outcome != "improved":
        return _finish_experiment(state, outcome, decision, "acceptance_criteria_not_met")
    # Erst jetzt atomare Promotion des genau einen Parameters.
    runtime_config.patch({pending["parameter"]: pending["candidate_value"]})
    state.setdefault("baselines", {})[pending["parameter"]] = pending["candidate_value"]
    state["last_improvement_at_utc"] = _now_iso()
    state["plateau_streak"] = 0
    state.pop("escalation_needed", None)
    return _finish_experiment(state, "improved", decision, "statistically_significant_improvement")


def _finish_experiment(state: dict, outcome: str, result: dict, reason: str) -> int:
    pending = state.get("pending", {})
    if outcome == "plateau":
        state["plateau_streak"] = int(state.get("plateau_streak", 0)) + 1
        if state["plateau_streak"] >= PLATEAU_ESCALATION_THRESHOLD:
            state["escalation_needed"] = True
    elif outcome != "insufficient_samples":
        state["plateau_streak"] = 0
    if outcome != "insufficient_samples":
        state["pending"] = {}
    state["last_experiment_result"] = {"experiment_id": pending.get("experiment_id"),
                                       "state": outcome, "reason": reason, **result}
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    _append_history({"ts": _now_iso(), "action": outcome, "reason": reason,
                     "experiment_id": pending.get("experiment_id"), "metrics": result})
    return 0

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
