"""P116 — Deterministische Reifegrad-Pruefung fuer FORECAST_EXPERIMENTS_ENABLED.

Fuenf Kriterien aus der Feld-2-Readiness-Checkliste (siehe HAILO_INTEGRATION.md
P116), davon vier datengetrieben pruefbar und eines (identische Actual-
Zuordnung Incumbent/Candidate) strukturell durch evaluate_paired_cases()
garantiert (experiment_contract.py, actual_mismatch-Guard) -- kein separater
Datencheck dafuer noetig.

Reine Auswertungsfunktion ohne Flask-/Netzwerkabhaengigkeiten, damit sie
unabhaengig vom Admin-Endpoint getestet werden kann.
"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT_MIN_COVERAGE_RATE = 0.9
DEFAULT_MAX_AMBIGUOUS_NEAREST_RATE = 0.05
DEFAULT_HISTORY_LOOKBACK = 20
PLATEAU_ESCALATION_THRESHOLD = 3  # deckungsgleich mit tools/tuning_apply.py


def _read_jsonl_tail(path: Path, n: int) -> list[dict]:
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    out = []
    for line in lines[-n:]:
        try:
            parsed = json.loads(line)
        except Exception:
            continue
        if isinstance(parsed, dict):
            out.append(parsed)
    return out


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def compute_readiness(
    eval_dir: "str | Path",
    *,
    min_coverage_rate: float = DEFAULT_MIN_COVERAGE_RATE,
    max_ambiguous_nearest_rate: float = DEFAULT_MAX_AMBIGUOUS_NEAREST_RATE,
    history_lookback: int = DEFAULT_HISTORY_LOOKBACK,
) -> dict:
    """Wertet accuracy_history.jsonl, tuning_history.jsonl und tuning_state.json
    aus einem Verzeichnis (Export oder Live-train_data/evaluation) aus und liefert
    einen strukturierten Reifegrad-Bericht mit fuenf Kriterien."""
    eval_dir = Path(eval_dir)

    rows = _read_jsonl_tail(eval_dir / "accuracy_history.jsonl", history_lookback)
    total_samples = sum(int(r.get("samples") or 0) for r in rows)
    total_verified = sum(int(r.get("verified") or 0) for r in rows)
    total_ambiguous = sum(int(r.get("ambiguous_nearest") or 0) for r in rows)
    coverage_rate = (total_verified / total_samples) if total_samples else None
    ambiguous_rate = (total_ambiguous / total_samples) if total_samples else None

    criterion_1 = {
        "id": "gold_match_coverage",
        "label": "Gold-Matches ausreichend",
        "ok": bool(coverage_rate is not None and coverage_rate >= min_coverage_rate),
        "value": coverage_rate,
        "threshold": min_coverage_rate,
        "detail": (f"{total_verified}/{total_samples} verifiziert ueber die letzten "
                   f"{len(rows)} Zeilen aus accuracy_history.jsonl") if rows
                  else "keine accuracy_history.jsonl-Daten gefunden",
    }
    criterion_2 = {
        "id": "ambiguous_nearest_rate",
        "label": "Nearest-Fallback-Anteil niedrig genug",
        "ok": bool(ambiguous_rate is not None and ambiguous_rate <= max_ambiguous_nearest_rate),
        "value": ambiguous_rate,
        "threshold": max_ambiguous_nearest_rate,
        "detail": (f"{total_ambiguous}/{total_samples} ambiguous_nearest ueber die letzten "
                   f"{len(rows)} Zeilen aus accuracy_history.jsonl") if rows
                  else "keine accuracy_history.jsonl-Daten gefunden",
    }

    tuning_rows = _read_jsonl_tail(eval_dir / "tuning_history.jsonl", 500)
    terminal_actions = {"improved", "rejected", "plateau"}
    matching = [r for r in tuning_rows if str(r.get("action")) in terminal_actions]
    criterion_3 = {
        "id": "completed_experiment_cycle",
        "label": "Mindestens ein abgeschlossener Experimentzyklus beobachtet",
        "ok": bool(matching),
        "value": len(matching),
        "threshold": 1,
        "detail": (f"{len(matching)} terminale(r) Eintrag/Eintraege "
                   f"(improved/rejected/plateau) in tuning_history.jsonl") if matching
                  else "noch kein abgeschlossener Zyklus in tuning_history.jsonl",
    }

    state = _read_json(eval_dir / "tuning_state.json")
    plateau_streak = int(state.get("plateau_streak", 0) or 0)
    escalation_needed = bool(state.get("escalation_needed", False))
    escalation_consistent = not (plateau_streak >= PLATEAU_ESCALATION_THRESHOLD and not escalation_needed)
    criterion_4 = {
        "id": "escalation_mechanism_consistent",
        "label": "Plateau-Eskalation intern konsistent",
        "ok": escalation_consistent,
        "value": plateau_streak,
        "threshold": PLATEAU_ESCALATION_THRESHOLD,
        "detail": f"plateau_streak={plateau_streak}, escalation_needed={escalation_needed}",
    }

    criterion_5 = {
        "id": "identical_actuals_guard",
        "label": "Identische Actual-Zuordnung Incumbent/Candidate",
        "ok": True,
        "value": None,
        "threshold": None,
        "detail": ("strukturell durch evaluate_paired_cases() garantiert "
                   "(experiment_contract.py, actual_mismatch-Guard) — kein separater "
                   "Datencheck noetig"),
        "structural": True,
    }

    criteria = [criterion_1, criterion_2, criterion_3, criterion_4, criterion_5]
    return {"overall_ready": all(c["ok"] for c in criteria), "criteria": criteria}
