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
import sys
from datetime import datetime, timezone
from pathlib import Path

# ─── Projektverzeichnis ──────────────────────────────────────────────
REPO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_DIR))

import config  # noqa: E402
import runtime_config  # noqa: E402

# ─── Pfade ────────────────────────────────────────────────────────────
EVAL_DIR = REPO_DIR / "train_data" / "evaluation"
STATE_FILE = EVAL_DIR / "tuning_state.json"
HISTORY_FILE = EVAL_DIR / "tuning_history.jsonl"
RESULT_FILE = EVAL_DIR / "analysis_result.json"
DRIFT_FILE = EVAL_DIR / "drift_status.json"
STATUS_FILE = EVAL_DIR / "local_analysis_status.json"  # B488: Freshness-Pruefung


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
    return {str(h): float(v.get("actual_mae_km", 999))
            for h, v in qt.items() if isinstance(v, dict)}


def _whitelist() -> dict:
    return getattr(config, "AUTONOMOUS_TUNING_PARAMS", {})


def _enabled() -> bool:
    rt = runtime_config.get("AUTONOMOUS_TUNING_ENABLED", None)
    if rt is not None:
        return bool(rt)
    return bool(getattr(config, "AUTONOMOUS_TUNING_ENABLED", False))


def validate_proposal(name: str, value: float) -> str | None:
    """Prueft einen Vorschlag gegen die Whitelist. None = ok, sonst Fehlertext."""
    wl = _whitelist()
    if name not in wl:
        return f"{name} nicht in AUTONOMOUS_TUNING_PARAMS"
    spec = wl[name]
    if not isinstance(value, (int, float)):
        return f"{name}: Wert {value!r} ist nicht numerisch"
    if value < spec["min"] or value > spec["max"]:
        return f"{name}: {value} ausserhalb [{spec['min']}, {spec['max']}]"
    offset = round((value - spec["min"]) / spec["step"], 6)
    if abs(offset - round(offset)) > 0.01:
        return f"{name}: {value} ist kein Vielfaches von step={spec['step']} ab min={spec['min']}"
    return None


def cmd_apply() -> int:
    """Nacht 1: Vorschlaege aus analysis_result.json lesen und anwenden."""
    if not _enabled():
        _log("AUTONOMOUS_TUNING_ENABLED=False — uebersprungen.")
        return 0
    status = _read_json(STATUS_FILE)
    if not status or status.get("state") != "ok":
        _log(f"Kein erfolgreicher lokaler Analyse-Lauf (state={status.get('state') if status else None}) — kein Apply.")
        return 0
    last_success_date = status.get("last_success_date")
    if not last_success_date:
        _log("Kein last_success_date im Status — kein Apply.")
        return 0
    prior_state = _read_json(STATE_FILE) or {}
    if prior_state.get("last_applied_success_date") == last_success_date:
        _log(f"Ergebnis vom {last_success_date} bereits angewandt — kein erneutes Apply.")
        return 0
    if prior_state.get("escalation_needed"):
        # P103: 3+ Plateaus in Folge — automatisches Tuning pausiert, bis im
        # Admin-Panel bestaetigt/zurueckgesetzt (POST /api/local_analysis/tuning/clear_escalation).
        _log("Eskalation aktiv (zu viele Plateaus in Folge) — Apply pausiert bis Bestaetigung im Admin-Panel.")
        return 0

    result = _read_json(RESULT_FILE)
    if not result:
        _log("Keine analysis_result.json vorhanden.")
        return 0
    proposals = result.get("tuning_proposals")
    if not proposals or not isinstance(proposals, dict):
        _log("Keine tuning_proposals in analysis_result.json.")
        return 0

    wl = _whitelist()
    state = _read_json(STATE_FILE) or {"baselines": {}, "pending": {}}
    applied = {}
    mae_before = _current_mae_by_horizon()

    for name, entry in proposals.items():
        if not isinstance(entry, dict):
            _log(f"SKIP {name}: kein dict")
            continue
        new_val = entry.get("value")
        reason = entry.get("reason", "")
        err = validate_proposal(name, new_val)
        if err:
            _log(f"ABGELEHNT: {err}")
            _append_history({"ts": _now_iso(), "action": "rejected",
                             "param": name, "value": new_val, "reason": err})
            continue
        current = float(runtime_config.get(name, getattr(config, name, wl[name]["min"])))
        state["baselines"].setdefault(name, current)
        state["pending"][name] = {"new": new_val, "old": current, "reason": reason}
        applied[name] = new_val
        _log(f"APPLY {name}: {current} -> {new_val} ({reason})")

    if not applied:
        _log("Keine gueltigen Vorschlaege.")
        return 0

    runtime_config.patch(applied)

    state["mae_before"] = mae_before
    state["applied_at"] = _now_iso()
    state["last_applied_success_date"] = last_success_date
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    for name, new_val in applied.items():
        old_val = state["pending"][name]["old"]
        _append_history({"ts": _now_iso(), "action": "applied",
                         "param": name, "old": old_val, "new": new_val,
                         "reason": state["pending"][name]["reason"],
                         "mae_before": mae_before})
    _log(f"{len(applied)} Parameter angewandt.")
    return 0


def cmd_verify() -> int:
    """Nacht 2: Ergebnis pruefen, ggf. Rollback."""
    if not _enabled():
        _log("AUTONOMOUS_TUNING_ENABLED=False — uebersprungen.")
        return 0
    state = _read_json(STATE_FILE)
    if not state or not state.get("pending"):
        _log("Kein pending-Tuning zum Verifizieren.")
        return 0

    mae_after = _current_mae_by_horizon()
    mae_before = state.get("mae_before", {})

    common = set(mae_before.keys()) & set(mae_after.keys())
    if not common:
        _log("WARNUNG: Keine gemeinsamen Horizonte — Rollback als Vorsichtsmassnahme.")
        return _rollback(state, mae_after, "no_common_horizons")

    avg_before = sum(mae_before[h] for h in common) / len(common)
    avg_after = sum(mae_after[h] for h in common) / len(common)
    delta_km = round(avg_after - avg_before, 3)

    if delta_km < 0:
        _log(f"AKZEPTIERT: MAE-Delta={delta_km} km. Baseline aktualisiert.")
        for name, info in state["pending"].items():
            state["baselines"][name] = info["new"]
            _append_history({"ts": _now_iso(), "action": "accepted",
                             "param": name, "value": info["new"],
                             "mae_before": avg_before, "mae_after": avg_after,
                             "delta_km": delta_km})
        state["pending"] = {}
        state.pop("mae_before", None)
        state.pop("applied_at", None)
        state["plateau_streak"] = 0  # P103: echte Verbesserung unterbricht die Plateau-Serie
        state.pop("escalation_needed", None)
        _check_stall(state)
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0
    elif delta_km == 0:
        # B490: Gleichstand ist kein nachgewiesener Erfolg (Plateau) und wird NICHT
        # in die Baseline uebernommen — Rollback auf den alten Wert, eigener Grund
        # fuer spaetere Auswertung.
        _log(f"PLATEAU: MAE-Delta=0.0 km — kein nachgewiesener Nutzen, Rollback.")
        state["plateau_streak"] = int(state.get("plateau_streak", 0)) + 1  # P103
        if state["plateau_streak"] >= PLATEAU_ESCALATION_THRESHOLD and not state.get("escalation_needed"):
            state["escalation_needed"] = True
            _append_history({"ts": _now_iso(), "action": "escalation_triggered",
                             "reason": f"{state['plateau_streak']} Plateaus in Folge — "
                                       f"automatisches Tuning pausiert, Ursachenklasse pruefen"})
            _log(f"ESKALATION: {state['plateau_streak']} Plateaus in Folge — Tuning pausiert.")
        _check_stall(state)
        return _rollback(state, mae_after, "plateau_no_measurable_improvement")
    else:
        _log(f"VERSCHLECHTERT: MAE-Delta=+{delta_km} km — Rollback.")
        state["plateau_streak"] = 0  # P103: Verschlechterung ist kein Plateau, zaehlt nicht mit
        _check_stall(state)
        return _rollback(state, mae_after, f"mae_worse_by_{delta_km}km")


def _rollback(state: dict, mae_after: dict, reason: str) -> int:
    rollback_values = {}
    for name, info in state["pending"].items():
        rollback_values[name] = info["old"]
        _append_history({"ts": _now_iso(), "action": "rollback",
                         "param": name, "old": info["new"], "new": info["old"],
                         "reason": reason, "mae_after": mae_after})
        _log(f"ROLLBACK {name}: {info['new']} -> {info['old']}")

    runtime_config.patch(rollback_values)
    state["pending"] = {}
    state.pop("mae_before", None)
    state.pop("applied_at", None)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
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
