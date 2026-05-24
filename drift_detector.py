"""
MAE-Trendüberwachung für WetterExtended-Modelle.

Analysiert accuracy_history.jsonl auf negativen MAE-Trend (Model-Drift).
Drift-Ergebnis wird in train_data/evaluation/drift_status.json persistiert
und via GET /api/drift im Admin-Panel angezeigt.

Drift-Kriterium:
  Gleitender MAE der letzten DRIFT_WINDOW_RECENT_H Stunden
  ist um > DRIFT_MAE_THRESHOLD_KM schlechter als der
  gleitende MAE der DRIFT_WINDOW_BASELINE_H davor.
  Mindestens DRIFT_MIN_POINTS Messpunkte müssen vorhanden sein.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import SAVE_PATHS
from debug_utils import debug_log

# Konfiguration
DRIFT_WINDOW_RECENT_H = int(os.getenv("DRIFT_WINDOW_RECENT_H", "24"))
DRIFT_WINDOW_BASELINE_H = int(os.getenv("DRIFT_WINDOW_BASELINE_H", "168"))
DRIFT_MAE_THRESHOLD_KM = float(os.getenv("DRIFT_MAE_THRESHOLD_KM", "2.0"))
DRIFT_MIN_POINTS = int(os.getenv("DRIFT_MIN_POINTS", "3"))

_EVAL_DIR = SAVE_PATHS.get("evaluation", "train_data/evaluation").rstrip("/")
_HISTORY_FILE = os.path.join(_EVAL_DIR, "accuracy_history.jsonl")
_STATUS_FILE = os.path.join(_EVAL_DIR, "drift_status.json")


def _read_history() -> list:
    """Liest accuracy_history.jsonl und gibt alle Einträge zurück."""
    if not os.path.exists(_HISTORY_FILE):
        return []
    out = []
    try:
        with open(_HISTORY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line.strip())
                    out.append(rec)
                except Exception:
                    continue
    except Exception as exc:
        debug_log(f"[DRIFT] Lesefehler history: {exc}")
    return out


def _parse_ts(rec: dict) -> Optional[datetime]:
    ts_str = rec.get("timestamp_utc", "")
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "")).replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _mean_mae(records: list) -> Optional[float]:
    """Mittlerer mae_km über alle Horizonte aller übergebenen Records."""
    values = []
    for rec in records:
        for horizon in rec.get("horizons", []):
            v = horizon.get("mae_km")
            if v is not None and isinstance(v, (int, float)) and v > 0:
                values.append(float(v))
    return sum(values) / len(values) if values else None


def check_drift() -> dict:
    """Prüft ob ein MAE-Drift vorliegt."""
    now = datetime.now(timezone.utc)
    recent_cutoff = now - timedelta(hours=DRIFT_WINDOW_RECENT_H)
    baseline_cutoff = now - timedelta(hours=DRIFT_WINDOW_BASELINE_H)

    all_records = _read_history()

    recent_recs = [r for r in all_records if _parse_ts(r) and _parse_ts(r) >= recent_cutoff]
    baseline_recs = [
        r for r in all_records
        if _parse_ts(r) and baseline_cutoff <= _parse_ts(r) < recent_cutoff
    ]

    mae_recent = _mean_mae(recent_recs)
    mae_baseline = _mean_mae(baseline_recs)

    result = {
        "drift_detected": False,
        "mae_recent_km": mae_recent,
        "mae_baseline_km": mae_baseline,
        "delta_km": None,
        "threshold_km": DRIFT_MAE_THRESHOLD_KM,
        "recent_points": len(recent_recs),
        "baseline_points": len(baseline_recs),
        "checked_at_utc": now.isoformat(timespec="seconds") + "Z",
        "message": "Zu wenige Messpunkte für Drift-Analyse.",
    }

    if (
        mae_recent is not None
        and mae_baseline is not None
        and len(recent_recs) >= DRIFT_MIN_POINTS
        and len(baseline_recs) >= DRIFT_MIN_POINTS
    ):
        delta = mae_recent - mae_baseline
        result["delta_km"] = round(delta, 3)

        if delta > DRIFT_MAE_THRESHOLD_KM:
            result["drift_detected"] = True
            result["message"] = (
                f"⚠️ Model-Drift erkannt: MAE verschlechtert um {delta:.2f} km "
                f"(recent={mae_recent:.2f} km vs. baseline={mae_baseline:.2f} km, "
                f"Threshold={DRIFT_MAE_THRESHOLD_KM} km)"
            )
            debug_log(f"[DRIFT] {result['message']}")
        else:
            result["message"] = (
                f"Model stabil: delta={delta:+.2f} km "
                f"(recent={mae_recent:.2f} km, baseline={mae_baseline:.2f} km)"
            )

    os.makedirs(_EVAL_DIR, exist_ok=True)
    try:
        with open(_STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        debug_log(f"[DRIFT] Konnte drift_status.json nicht schreiben: {exc}")

    return result


def check_and_alert(eval_result: Optional[dict] = None) -> dict:
    """
    Führt Drift-Check durch und sendet E-Mail-Alarm wenn Drift erkannt.
    eval_result: aktuelles Ergebnis von evaluate_all() (optional, nur für Logging).
    """
    _ = eval_result
    status = check_drift()

    if status.get("drift_detected"):
        try:
            from email_notifier import send_drift_alert

            send_drift_alert(status)
        except ImportError:
            debug_log("[DRIFT] email_notifier.send_drift_alert nicht verfügbar — kein Mail-Alarm")
        except Exception as exc:
            debug_log(f"[DRIFT] Mail-Alarm Fehler: {exc}")

    return status


def load_status() -> dict:
    """Lädt letzten Drift-Status aus drift_status.json (für API-Endpoint)."""
    if not os.path.exists(_STATUS_FILE):
        return {"drift_detected": False, "message": "Noch kein Drift-Check durchgeführt."}
    try:
        with open(_STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"drift_detected": False, "message": "Drift-Status nicht lesbar."}
