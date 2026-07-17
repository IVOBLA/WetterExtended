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

from config import (
    SAVE_PATHS,
    QUALITY_TARGET_MAE_KM_CONFIGURABLE_DEFAULT,
    QUALITY_TARGET_MAE_KM_FIXED,
    DRIFT_DIRECTION_P90_MAX_DEG,
    DRIFT_SPEED_P90_MAX_KMH,
    DRIFT_DIRECTION_SPEED_MIN_POINTS,
)
import runtime_config as _runtime_cfg
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
_MODELS_BASE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "train_data", "models"
)


def _horizon_is_fixed_target(horizon_key: str) -> bool:
    """B286: Massgeblich ist die Zieldefinition (<=30 Min -> <1km), NICHT die
    Frage, ob der Horizont einer der Standardwerte 10/20/30 ist. Auch
    benutzerdefinierte Horizonte wie h15/h25 unterliegen der festen Vorgabe."""
    try:
        return int(horizon_key) <= 30
    except (TypeError, ValueError):
        return False


def _runtime_float(key: str, default: float) -> float:
    try:
        if _runtime_cfg is not None:
            value = _runtime_cfg.get(key, default)
            if value is not None:
                return float(value)
    except Exception as exc:
        debug_log(f"[DRIFT] Runtime-Float {key} nicht lesbar: {exc}")
    return float(default)


def _runtime_int(key: str, default: int) -> int:
    try:
        if _runtime_cfg is not None:
            value = _runtime_cfg.get(key, default)
            if value is not None:
                return int(value)
    except Exception as exc:
        debug_log(f"[DRIFT] Runtime-Int {key} nicht lesbar: {exc}")
    return int(default)


def _quality_target_for_horizon(horizon_key: str) -> float:
    """P70/B286: <=30-Min-Ziele sind IMMER fest (numerisch geprüft, nicht nur
    für 10/20/30), unabhängig von konfigurierten Horizonten. >30-Min-Horizonte
    sind administrierbar via Runtime-Override."""
    horizon_key = str(horizon_key)
    if _horizon_is_fixed_target(horizon_key):
        return QUALITY_TARGET_MAE_KM_FIXED.get(horizon_key, QUALITY_TARGET_MAE_KM_FIXED.get("30", 1.0))
    runtime_val = _runtime_cfg.get(f"QUALITY_TARGET_MAE_KM_{horizon_key}") if _runtime_cfg else None
    if runtime_val is not None:
        return float(runtime_val)
    return QUALITY_TARGET_MAE_KM_CONFIGURABLE_DEFAULT.get(horizon_key, 2.0)


def _mae_by_horizon(records: list) -> dict[float, float]:
    """Mittlerer mae_km je Horizont. Schlüssel: Horizont in Minuten."""
    values: dict[float, list[float]] = {}
    for rec in records:
        for horizon in rec.get("horizons", []):
            h = horizon.get("horizon")
            v = horizon.get("mae_km")
            if h is None or not isinstance(v, (int, float)) or v <= 0:
                continue
            try:
                key = float(h)
            except (TypeError, ValueError):
                continue
            values.setdefault(key, []).append(float(v))
    return {h: round(sum(vals) / len(vals), 3) for h, vals in values.items() if vals}


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
    mae_recent_by_horizon = _mae_by_horizon(recent_recs)
    mae_baseline_by_horizon = _mae_by_horizon(baseline_recs)
    common_horizons = sorted(mae_recent_by_horizon.keys() & mae_baseline_by_horizon.keys())
    skipped_horizons = sorted(mae_recent_by_horizon.keys() ^ mae_baseline_by_horizon.keys())
    delta_by_horizon = {
        horizon: round(mae_recent_by_horizon[horizon] - mae_baseline_by_horizon[horizon], 3)
        for horizon in common_horizons
    }
    short_deltas = {
        horizon: delta
        for horizon, delta in delta_by_horizon.items()
        if horizon <= DRIFT_SHORT_HORIZON_MAX_MIN
    }
    triggering_horizons = sorted(
        horizon for horizon, delta in short_deltas.items() if delta > DRIFT_MAE_THRESHOLD_KM
    )

    result = {
        "drift_detected": False,
        "drift_reason": None,
        "mae_recent_km": mae_recent,
        "mae_baseline_km": mae_baseline,
        "mae_recent_short_km": mae_recent_short,
        "mae_recent_by_horizon": mae_recent_by_horizon,
        "mae_baseline_by_horizon": mae_baseline_by_horizon,
        "delta_by_horizon": delta_by_horizon,
        "triggering_horizons": triggering_horizons,
        "skipped_horizons_not_in_both_windows": skipped_horizons,
        "short_horizon_max_min": DRIFT_SHORT_HORIZON_MAX_MIN,
        "abs_threshold_km": DRIFT_MAE_ABS_MAX_KM,
        "quality_target_met": None,
        "quality_target_by_horizon": {},
        "quality_target_violation_horizon": None,
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

    if len(recent_recs) >= DRIFT_MIN_POINTS and len(baseline_recs) >= DRIFT_MIN_POINTS:
        delta = max(short_deltas.values()) if short_deltas else None
        result["delta_km"] = delta

        if triggering_horizons:
            result["drift_detected"] = True
            result["drift_reason"] = "relative"
            result["model_status"] = "drift"
            result["message"] = (
                f"⚠️ Model-Drift erkannt: Kurzhorizont-MAE verschlechtert um {delta:.2f} km "
                f"(Horizonte={triggering_horizons}, "
                f"Threshold={DRIFT_MAE_THRESHOLD_KM} km)"
            )
            debug_log(f"[DRIFT] {result['message']}")
        elif delta is None:
            result["model_status"] = "unknown"
            result["message"] = "Keine gemeinsamen Kurzhorizonte für relative Drift-Analyse."
        elif all(value < 0 for value in short_deltas.values()):
            result["model_status"] = "improved"
            result["message"] = (
                f"ℹ️ Modellqualität verbessert: delta={delta:+.2f} km "
                f"(größtes Kurzhorizont-Delta={delta:+.2f} km)"
            )
        else:
            result["model_status"] = "stable"
            result["message"] = (
                f"Model stabil: delta={delta:+.2f} km "
                f"(größtes Kurzhorizont-Delta={delta:+.2f} km)"
            )

    if len(recent_recs) >= DRIFT_MIN_POINTS:
        mae_by_horizon = _mae_by_horizon(recent_recs)
        quality_target_by_horizon = {}
        for h, actual in mae_by_horizon.items():
            horizon_key = str(int(h)) if h.is_integer() else str(h)
            target = _quality_target_for_horizon(horizon_key)
            quality_target_by_horizon[horizon_key] = {
                "target_km": target,
                "actual_mae_km": actual,
                "met": actual <= target,
                "editable": not _horizon_is_fixed_target(horizon_key),
            }
        violation_horizon = next(
            (str(int(h)) if h.is_integer() else str(h) for h, actual in mae_by_horizon.items()
             if actual is not None and actual > _quality_target_for_horizon(str(int(h)) if h.is_integer() else str(h))),
            None,
        )
        result["quality_target_by_horizon"] = quality_target_by_horizon
        result["quality_target_violation_horizon"] = violation_horizon
        if quality_target_by_horizon:
            quality_missed = violation_horizon is not None
            result["quality_target_met"] = all(v["met"] for v in quality_target_by_horizon.values())
            result["quality_status"] = "missed" if quality_missed else "met"
            if quality_missed:
                missed = quality_target_by_horizon[violation_horizon]
                result["quality_message"] = (
                    "Das Modell verbessert sich, erreicht die konfigurierte Zielqualität jedoch noch nicht."
                    if mae_recent is not None and mae_baseline is not None and mae_recent <= mae_baseline
                    else f"Qualitätsziel noch nicht erreicht: MAE(h{violation_horizon}) "
                         f"= {missed['actual_mae_km']:.2f} km > {missed['target_km']} km."
                )
            else:
                result["quality_message"] = "Qualitätsziel erreicht."


    # P71: Richtungs-/Geschwindigkeitsfehler als eigenstaendige Drift-Kennzahl.
    # Quelle: direction_stats_by_horizon / speed_stats_by_horizon aus der
    # juengsten accuracy_history-Zeile mit ausreichenden Samples auf Kurzhorizonten.
    try:
        _dir_thr = _runtime_float("DRIFT_DIRECTION_P90_MAX_DEG", DRIFT_DIRECTION_P90_MAX_DEG)
        _spd_thr = _runtime_float("DRIFT_SPEED_P90_MAX_KMH", DRIFT_SPEED_P90_MAX_KMH)
        _min_pts = _runtime_int("DRIFT_DIRECTION_SPEED_MIN_POINTS", DRIFT_DIRECTION_SPEED_MIN_POINTS)
        _latest = None
        for _rec in reversed(all_records):
            if _rec.get("direction_stats_by_horizon") or _rec.get("speed_stats_by_horizon"):
                _latest = _rec
                break
        _dir_by_h = {}
        _spd_by_h = {}
        _dir_alarm = False
        _spd_alarm = False
        if _latest:
            _dstats = _latest.get("direction_stats_by_horizon", {}) or {}
            _sstats = _latest.get("speed_stats_by_horizon", {}) or {}
            for _hk, _v in _dstats.items():
                try:
                    if float(_hk) > DRIFT_SHORT_HORIZON_MAX_MIN:
                        continue
                except (TypeError, ValueError):
                    continue
                _p90 = _v.get("p90_direction_error_deg")
                _median = _v.get("median_direction_error_deg")
                _n = int(_v.get("count", _v.get("samples", _v.get("n", 0))) or 0)
                _dir_by_h[_hk] = {"median_deg": _median, "p90_deg": _p90, "samples": _n, "threshold_deg": _dir_thr}
                if _p90 is not None and _n >= _min_pts and _p90 > _dir_thr:
                    _dir_alarm = True
            for _hk, _v in _sstats.items():
                try:
                    if float(_hk) > DRIFT_SHORT_HORIZON_MAX_MIN:
                        continue
                except (TypeError, ValueError):
                    continue
                _p90 = _v.get("p90_speed_error_kmh")
                _median = _v.get("median_speed_error_kmh")
                _n = int(_v.get("count", _v.get("samples", _v.get("n", 0))) or 0)
                _spd_by_h[_hk] = {"median_kmh": _median, "p90_kmh": _p90, "samples": _n, "threshold_kmh": _spd_thr}
                if _p90 is not None and _n >= _min_pts and _p90 > _spd_thr:
                    _spd_alarm = True
        result["direction_drift_by_horizon"] = _dir_by_h
        result["speed_drift_by_horizon"] = _spd_by_h
        result["direction_drift_alarm"] = _dir_alarm
        result["speed_drift_alarm"] = _spd_alarm
    except Exception as _exc:
        debug_log(f"[DRIFT][P71] Richtungs-/Speed-Auswertung fehlgeschlagen: {_exc}")
        result["direction_drift_by_horizon"] = {}
        result["speed_drift_by_horizon"] = {}
        result["direction_drift_alarm"] = False
        result["speed_drift_alarm"] = False

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


def _ml_delivery_suppression_reason() -> Optional[str]:
    """Liefert den Grund, aus dem kein ausgeliefertes ML-Modell belegt ist."""
    if not os.path.isdir(os.path.join(_MODELS_BASE, "current")):
        return "no_promoted_model"

    records = _read_history()
    if not records:
        return "delivered_mode_unreadable"
    delivered = records[-1].get("delivered_mode_counts")
    if not isinstance(delivered, dict):
        return "delivered_mode_unreadable"

    try:
        ml_count = sum(
            int(count or 0)
            for horizon_counts in delivered.values()
            if isinstance(horizon_counts, dict)
            for mode, count in horizon_counts.items()
            if mode == "ml"
        )
    except (TypeError, ValueError):
        return "delivered_mode_unreadable"
    return None if ml_count > 0 else "delivered_mode_kinematic_only"


def _ml_model_is_delivered() -> bool:
    """True nur, wenn tatsaechlich ein ML-Modell ausgeliefert wird."""
    return _ml_delivery_suppression_reason() is None


def _persist_status(status: dict) -> None:
    """Schreibt einen nach dem Drift-Check ergänzten Status bestmöglich zurück."""
    os.makedirs(_EVAL_DIR, exist_ok=True)
    try:
        with open(_STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(status, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        debug_log(f"[DRIFT] Konnte drift_status.json nicht schreiben: {exc}")


def check_and_alert(eval_result: Optional[dict] = None) -> dict:
    """
    Fuehrt Drift-Check durch und sendet E-Mail-Alarm wenn Drift erkannt.
    eval_result: aktuelles Ergebnis von evaluate_all() (optional, nur fuer Logging).
    Kein Alarm im reinen Fallback-Modus (keine ML-Modelle vorhanden).
    """
    _ = eval_result
    status = check_drift()

    if status.get("drift_detected"):
        if not _ml_model_is_delivered():
            suppression_reason = _ml_delivery_suppression_reason()
            status["alert_suppressed"] = True
            status["alert_suppression_reason"] = suppression_reason
            _persist_status(status)
            debug_log(
                f"[DRIFT] Drift-Alarm unterdrueckt ({suppression_reason}) — "
                "kein ausgeliefertes ML-Modell eindeutig belegt."
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
