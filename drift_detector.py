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
from utils import utc_iso_z

# Konfiguration
DRIFT_WINDOW_RECENT_H = int(os.getenv("DRIFT_WINDOW_RECENT_H", "24"))
DRIFT_WINDOW_BASELINE_H = int(os.getenv("DRIFT_WINDOW_BASELINE_H", "168"))
DRIFT_MAE_THRESHOLD_KM = float(os.getenv("DRIFT_MAE_THRESHOLD_KM", "2.0"))
DRIFT_MIN_POINTS = int(os.getenv("DRIFT_MIN_POINTS", "3"))
# Absoluter Kurzhorizont-Grenzwert: Qualitätsziel, kein Drift-Auslöser.
# Zielverletzungen werden separat im Status ausgewiesen.
DRIFT_MAE_ABS_MAX_KM = float(os.getenv("DRIFT_MAE_ABS_MAX_KM", "1.0"))
DRIFT_SHORT_HORIZON_MAX_MIN = float(os.getenv("DRIFT_SHORT_HORIZON_MAX_MIN", "30"))

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


def _mean_mae_for_horizons(records: list, max_horizon_min: Optional[float] = None) -> Optional[float]:
    """Mittlerer mae_km über Horizonte aller Records.

    Mit max_horizon_min werden NUR Horizonte einbezogen, deren `horizon` (Minuten)
    <= max_horizon_min ist (B165: Kurzhorizont-Wächter). Ohne Angabe: alle Horizonte.
    """
    values = []
    for rec in records:
        for horizon in rec.get("horizons", []):
            if max_horizon_min is not None:
                _h = horizon.get("horizon")
                try:
                    if _h is None or float(_h) > float(max_horizon_min):
                        continue
                except (TypeError, ValueError):
                    continue
            v = horizon.get("mae_km")
            if v is not None and isinstance(v, (int, float)) and v > 0:
                values.append(float(v))
    return sum(values) / len(values) if values else None


def _mean_mae(records: list) -> Optional[float]:
    """Mittlerer mae_km über ALLE Horizonte aller Records (Rückwärtskompatibilität)."""
    return _mean_mae_for_horizons(records, None)


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
    mae_recent_short = _mean_mae_for_horizons(recent_recs, DRIFT_SHORT_HORIZON_MAX_MIN)

    result = {
        "drift_detected": False,
        "drift_reason": None,
        "mae_recent_km": mae_recent,
        "mae_baseline_km": mae_baseline,
        "mae_recent_short_km": mae_recent_short,
        "short_horizon_max_min": DRIFT_SHORT_HORIZON_MAX_MIN,
        "abs_threshold_km": DRIFT_MAE_ABS_MAX_KM,
        "quality_target_met": None,
        "bias_by_horizon": {},
        "quality_status": "unknown",
        "quality_message": "Zu wenige Kurzhorizont-Messpunkte für Qualitätsziel-Auswertung.",
        "model_status": "unknown",
        "delta_km": None,
        "threshold_km": DRIFT_MAE_THRESHOLD_KM,
        "recent_points": len(recent_recs),
        "baseline_points": len(baseline_recs),
        "checked_at_utc": utc_iso_z(now),
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
            result["drift_reason"] = "relative"
            result["model_status"] = "drift"
            result["message"] = (
                f"⚠️ Model-Drift erkannt: MAE verschlechtert um {delta:.2f} km "
                f"(recent={mae_recent:.2f} km vs. baseline={mae_baseline:.2f} km, "
                f"Threshold={DRIFT_MAE_THRESHOLD_KM} km)"
            )
            debug_log(f"[DRIFT] {result['message']}")
        elif mae_recent < mae_baseline:
            result["model_status"] = "improved"
            result["message"] = (
                f"ℹ️ Modellqualität verbessert: delta={delta:+.2f} km "
                f"(recent={mae_recent:.2f} km, baseline={mae_baseline:.2f} km)"
            )
        else:
            result["model_status"] = "stable"
            result["message"] = (
                f"Model stabil: delta={delta:+.2f} km "
                f"(recent={mae_recent:.2f} km, baseline={mae_baseline:.2f} km)"
            )

    if mae_recent_short is not None and len(recent_recs) >= DRIFT_MIN_POINTS:
        quality_missed = mae_recent_short > DRIFT_MAE_ABS_MAX_KM
        result["quality_target_met"] = not quality_missed
        result["quality_status"] = "missed" if quality_missed else "met"
        if quality_missed:
            result["quality_message"] = (
                "Das Modell verbessert sich, erreicht die konfigurierte Zielqualität jedoch noch nicht."
                if mae_recent is not None and mae_baseline is not None and mae_recent <= mae_baseline
                else f"Qualitätsziel noch nicht erreicht: MAE(≤{int(DRIFT_SHORT_HORIZON_MAX_MIN)} min) "
                     f"= {mae_recent_short:.2f} km > {DRIFT_MAE_ABS_MAX_KM} km."
            )
        else:
            result["quality_message"] = "Qualitätsziel erreicht."


    try:
        from forecast_error_diagnosis import build_forecast_error_diagnosis, load_forecast_bias_status
        result["bias_by_horizon"] = load_forecast_bias_status().get("bias_by_horizon", {})
        _diag = build_forecast_error_diagnosis(
            details_path=os.path.join(_EVAL_DIR, "forecast_error_details.jsonl"),
            accuracy_history_path=_HISTORY_FILE,
            hours=DRIFT_WINDOW_RECENT_H,
        )
        result["diagnosis_summary"] = {
            "severity": _diag.get("severity"),
            "primary_findings": _diag.get("primary_findings", []),
            "top_recommendation": (_diag.get("recommendations") or [None])[0],
        }
    except Exception as exc:
        debug_log(f"[DRIFT] Forecast-Error-Diagnose nicht verfügbar: {exc}")

    os.makedirs(_EVAL_DIR, exist_ok=True)
    try:
        with open(_STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        debug_log(f"[DRIFT] Konnte drift_status.json nicht schreiben: {exc}")

    return result


def _has_ml_model() -> bool:
    """
    Gibt True zurueck wenn mindestens eine trainierte Modell-Version vorhanden ist.
    Ohne ML-Modell ist Drift-Detection nicht relevant (kinematischer Fallback-Modus).
    Prueft train_data/models/current/ (Symlink/Dir) und train_data/models/v_*-Verzeichnisse.
    """
    import glob as _glob

    models_base = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "train_data", "models"
    )
    if not os.path.isdir(models_base):
        return False
    if os.path.isdir(os.path.join(models_base, "current")):
        return True
    return len(_glob.glob(os.path.join(models_base, "v_*"))) > 0


def check_and_alert(eval_result: Optional[dict] = None) -> dict:
    """
    Fuehrt Drift-Check durch und sendet E-Mail-Alarm wenn Drift erkannt.
    eval_result: aktuelles Ergebnis von evaluate_all() (optional, nur fuer Logging).
    Kein Alarm im reinen Fallback-Modus (keine ML-Modelle vorhanden).
    """
    _ = eval_result
    status = check_drift()

    if status.get("drift_detected"):
        if not _has_ml_model():
            debug_log(
                "[DRIFT] Drift erkannt, aber kein ML-Modell vorhanden — "
                "kein E-Mail-Alarm (kinematischer Fallback-Modus aktiv)."
            )
        else:
            try:
                from email_notifier import send_drift_alert

                send_drift_alert(status)
            except ImportError:
                debug_log(
                    "[DRIFT] email_notifier.send_drift_alert nicht verfuegbar — "
                    "kein Mail-Alarm"
                )
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
