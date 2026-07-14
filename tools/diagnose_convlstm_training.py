#!/usr/bin/env python3
"""B357: Offline-Auswertung der ConvLSTM-Trainings-Telemetrie (B356/B357) fuer
den 24h-Debug-Export. Liest convlstm_training_runs.jsonl (Kind- UND
Eltern-Fallback-Eintraege), fasst die letzten Laeufe zusammen und markiert,
wenn ein Lauf trotz B356-Kaskade vom System-OOM-Killer beendet wurde. Reine
Beobachtung/Statistik, kein Verhaltens-Fix."""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    from config import SAVE_PATHS
except Exception:  # pragma: no cover
    SAVE_PATHS = {"evaluation": "train_data/evaluation"}

from export_diagnosis import utc_now_z

LATEST_NAME = "convlstm_training_diagnosis_latest.json"
ERROR_NAME = "convlstm_training_diagnosis_error.json"
# B357: das Training laeuft woechentlich — ein 24h-Fenster wuerde die meisten
# Tage 0 Zeilen liefern. Default deckt > 1 Woche ab, damit der letzte Lauf
# fast immer erfasst wird.
_DEFAULT_LOOKBACK_HOURS = 24 * 10
_MAX_RECENT_RUNS = 5


def _resolve_save_path(base_dir: Path, key: str, default: str, save_paths: dict | None = None) -> Path:
    paths = save_paths or SAVE_PATHS
    raw = Path(paths.get(key, default))
    return raw if raw.is_absolute() else base_dir / raw


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=_DEFAULT_LOOKBACK_HOURS)
    parser.add_argument("--base-dir", type=str, default=".")
    parser.add_argument("--evaluation-dir", type=str, default=None)
    args = parser.parse_args()

    base_dir = Path(args.base_dir).resolve()
    ev_dir = Path(args.evaluation_dir) if args.evaluation_dir else _resolve_save_path(base_dir, "evaluation", "train_data/evaluation")
    ev_dir.mkdir(parents=True, exist_ok=True)
    latest_path = ev_dir / LATEST_NAME
    error_path = ev_dir / ERROR_NAME

    try:
        runs = _read_jsonl(ev_dir / "convlstm_training_runs.jsonl")
        runs.sort(key=lambda r: str(r.get("timestamp_utc", "")))
        recent = runs[-_MAX_RECENT_RUNS:]
        last_run = recent[-1] if recent else None

        important_findings: list[str] = []
        recommendations: list[str] = []

        if last_run is None:
            important_findings.append("Noch kein ConvLSTM-Trainingslauf mit B357-Telemetrie erfasst.")
            recommendations.append("Naechsten planmaessigen convlstm_weekly-Lauf abwarten.")
        else:
            outcome = last_run.get("outcome")
            if outcome == "success":
                bs = last_run.get("batch_size_used")
                attempts = last_run.get("batch_size_cascade_attempts")
                if attempts and attempts > 1:
                    important_findings.append(
                        f"Letzter Lauf erfolgreich, aber erst nach Kaskade auf batch_size={bs} "
                        f"({attempts} Versuche) — RAM ist knapp, B356-Sicherheitsmarge beobachten."
                    )
                else:
                    important_findings.append(f"Letzter Lauf erfolgreich mit batch_size={bs} im ersten Versuch.")
            elif outcome == "system_oom_kill":
                important_findings.append(
                    "Letzter Lauf wurde trotz dynamischem RLIMIT_AS (B356) vom System-OOM-Killer "
                    "beendet (rc=-9/137) — selbst batch_size=1 passt offenbar nicht in den frei "
                    "verfuegbaren RAM."
                )
                recommendations.append(
                    "CONVLSTM_MAX_FRAMES senken, Modellgroesse/Aufloesung reduzieren, oder "
                    "convlstm_weekly auf ein Zeitfenster mit weniger Fremdlast legen."
                )
            elif outcome == "timeout":
                important_findings.append("Letzter Lauf wurde durch CONVLSTM_TRAIN_TIMEOUT_S abgebrochen.")
                recommendations.append("Timeout oder Epochenzahl pruefen, falls das Training regelmaessig zu lange braeuchte.")
            elif str(outcome).startswith("skipped_"):
                important_findings.append(f"Letzter Lauf uebersprungen: {outcome}.")
            elif outcome == "exception":
                important_findings.append(
                    f"Letzter Lauf mit Exception beendet: {last_run.get('error_type')}: {last_run.get('error')}"
                )
            else:
                important_findings.append(f"Letzter Lauf mit unbekanntem Outcome: {outcome}.")

        success_count = sum(1 for r in recent if r.get("outcome") == "success")
        payload = {
            "status": "ok",
            "timestamp_utc": utc_now_z(),
            "runs_considered": len(recent),
            "success_rate_recent": round(success_count / len(recent), 2) if recent else None,
            "last_run": last_run,
            "recent_runs": recent,
            "important_findings": important_findings,
            "recommendations": recommendations,
        }
        latest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        error_path.unlink(missing_ok=True)
        return 0
    except Exception as exc:  # noqa: BLE001 - Export darf nicht blockieren.
        payload = {
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "timestamp_utc": utc_now_z(),
        }
        error_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        latest_path.unlink(missing_ok=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
