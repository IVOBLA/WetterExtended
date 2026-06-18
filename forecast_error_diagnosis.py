"""Offline-Diagnose der Forecast-Error-Breakdowns (B214).

Dieses Modul wertet ausschließlich lokal vorhandene B211-Dateien aus und nutzt
keine externen Requests.
"""
from __future__ import annotations

import json
import math
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from config import SAVE_PATHS
except Exception:  # pragma: no cover
    SAVE_PATHS = {"evaluation": "train_data/evaluation"}

EVAL_DIR = Path(SAVE_PATHS.get("evaluation", "train_data/evaluation"))
DETAILS_FILE = EVAL_DIR / "forecast_error_details.jsonl"
HISTORY_FILE = EVAL_DIR / "accuracy_history.jsonl"
DIAGNOSIS_FILE = EVAL_DIR / "forecast_error_diagnosis.json"
HEALTH_FILE = EVAL_DIR / "motion_pipeline_health.json"
SHORT_HORIZON_MAX_MIN = 30
TARGET_MAE_KM = 1.0

RECOMMENDATIONS = {
    "ml_worse_than_kinematic": "ML-Gating/Fallback prüfen: ML nur verwenden, wenn aktuelle Modellqualität besser als kinematic ist.",
    "kinematic_worse_than_ml": "ML häufiger nutzen, sofern Modell frisch und Feature-Kompatibilität passt.",
    "direction_error_dominates": "Bewegungsrichtung prüfen: Optical-Flow-Vektor, Pixel/Geo-Transformation, Zell-ID-Matching und Orographie-/Windfeatures analysieren.",
    "speed_error_dominates": "Geschwindigkeitsbetrag prüfen: Frame-Δt, optflow frame minutes, velocity smoothing.",
    "nearest_match_problem": "Verifikation/Lineage-Matching prüfen: Split/Merge, ID-Verlust, cell_id-Verifikation priorisieren.",
    "cell_id_matching_needed": "Forecast-Verifikation auf cell_id priorisieren, sobald Lineage stabil ist.",
    "coverage_limited": "Radarframe-Coverage prüfen: ARSO-Frame-Takt, not_new-Skip, Exportfenster.",
    "low_sample_count": "Mehr Daten sammeln, Diagnose nicht überinterpretieren.",
    "outlier_dominated": "Worst-Forecasts prüfen: Einzelne Split/Merge-/Matchingfälle dominieren MAE.",
    "motion_pipeline_ok_but_accuracy_bad": "Nicht pySTEPS priorisieren; Fokus auf Richtung, Matching, ML-Gating oder Schwerpunktjitter.",
}
FINDINGS = {
    "ml_worse_than_kinematic": "ML forecast performs worse than kinematic fallback.",
    "kinematic_worse_than_ml": "Kinematic fallback performs worse than ML forecast.",
    "direction_error_dominates": "Forecast direction error probably dominates short-horizon drift.",
    "speed_error_dominates": "Forecast speed error probably dominates short-horizon drift.",
    "nearest_match_problem": "Nearest-neighbor verification is probably inflating errors.",
    "cell_id_matching_needed": "cell_id matching is probably needed for more stable verification.",
    "coverage_limited": "Target-frame coverage is probably limiting diagnosis quality.",
    "low_sample_count": "Low sample count: findings are only weak indications.",
    "outlier_dominated": "A few outlier forecasts probably dominate MAE.",
    "motion_pipeline_ok_but_accuracy_bad": "Motion pipeline appears healthy, but forecast accuracy is still bad.",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _read_jsonl(path: Path, hours: int, ts_keys: tuple[str, ...]) -> list[dict]:
    if not path.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if not isinstance(rec, dict):
            continue
        ts = next((_parse_ts(rec.get(k)) for k in ts_keys if _parse_ts(rec.get(k))), None)
        if ts is None or ts >= cutoff:
            rows.append(rec)
    return rows


def _f(v: Any) -> float | None:
    try:
        if v is None:
            return None
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _pct(values: list[float], p: float) -> float | None:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    idx = min(len(vals) - 1, max(0, math.ceil(p / 100.0 * len(vals)) - 1))
    return vals[idx]


def _validate_detail_time_order(row: dict) -> tuple[bool, str | None]:
    forecast_created = _parse_ts(row.get("forecast_created_at_utc"))
    verified_at = _parse_ts(row.get("verified_at_utc"))
    target_ts = _parse_ts(row.get("target_timestamp_utc"))
    if forecast_created is not None and verified_at is not None and verified_at < forecast_created:
        return False, "invalid_time_order"
    if forecast_created is not None and target_ts is not None and target_ts < forecast_created:
        return False, "invalid_time_order"
    if target_ts is not None and verified_at is not None and target_ts > verified_at:
        return False, "invalid_time_order"
    return True, None


def _filter_valid_details(rows: list[dict]) -> tuple[list[dict], dict[str, int]]:
    valid = []
    invalid_counts: dict[str, int] = {}
    for row in rows:
        ok, reason = _validate_detail_time_order(row)
        if ok:
            valid.append(row)
            continue
        invalid_counts[reason or "invalid_detail"] = invalid_counts.get(reason or "invalid_detail", 0) + 1
    return valid, invalid_counts


def _stats(rows: list[dict], key: str = "forecast_error_km") -> dict:
    vals = [_f(r.get(key)) for r in rows]
    vals = [v for v in vals if v is not None]
    if not vals:
        return {"verified": 0, "mae_km": None}
    return {"verified": len(vals), "mae_km": round(sum(vals) / len(vals), 3), "median_km": round(statistics.median(vals), 3), "p90_km": round(_pct(vals, 90), 3)}


def _add(cands: list[dict], code: str, severity: str, confidence: float, evidence: dict) -> None:
    cands.append({"code": code, "severity": severity, "confidence": round(confidence, 2), "evidence": evidence, "recommendation": RECOMMENDATIONS[code]})


def _confidence(n: int, strong: bool = False) -> float:
    if n < 10:
        return 0.3
    if n < 30:
        return 0.6 if not strong else 0.75
    return 0.85 if not strong else 0.92


def build_forecast_error_diagnosis(*, details_path: str | Path = DETAILS_FILE, accuracy_history_path: str | Path = HISTORY_FILE, hours: int = 24) -> dict:
    details_path = Path(details_path); history_path = Path(accuracy_history_path)
    base = {
        "checked_at_utc": _now(), "hours": hours, "status": "ok",
        "sample_counts": {"details": 0, "verified_short": 0, "verified_total": 0},
        "invalid_detail_counts": {},
        "primary_findings": [], "recommendations": [], "severity": "ok", "root_cause_candidates": [],
        "mode_comparison": {}, "source_comparison": {}, "match_type_comparison": {},
        "direction_diagnosis": {}, "speed_diagnosis": {}, "coverage_diagnosis": {}, "worst_forecasts": [],
    }
    if not details_path.exists():
        base.update({"status": "missing", "severity": "watch", "recommendations": ["B211 muss zuerst Daten sammeln."]})
        return base
    details, invalid_detail_counts = _filter_valid_details(_read_jsonl(details_path, hours, ("verified_at_utc", "target_timestamp_utc", "forecast_created_at_utc")))
    history = _read_jsonl(history_path, hours, ("timestamp_utc",)) if history_path.exists() else []
    base["invalid_detail_counts"] = invalid_detail_counts
    short = [r for r in details if (_f(r.get("horizon_min")) or 9999) <= SHORT_HORIZON_MAX_MIN]
    verified = [r for r in details if _f(r.get("forecast_error_km")) is not None]
    verified_short = [r for r in short if _f(r.get("forecast_error_km")) is not None]
    base["sample_counts"] = {"details": len(details), "verified_short": len(verified_short), "verified_total": len(verified)}
    if not details:
        base.update({"status": "insufficient_data", "severity": "watch", "recommendations": ["Mehr Daten sammeln, Diagnose nicht überinterpretieren."]})
        return base

    def group(field: str) -> dict:
        out = {}
        for r in verified_short:
            out.setdefault(str(r.get(field) or "unknown"), []).append(r)
        return {k: _stats(v) for k, v in out.items()}

    mode = group("forecast_mode"); source = group("kinematic_source"); match = group("match_type")
    base["mode_comparison"] = mode; base["source_comparison"] = source; base["match_type_comparison"] = match
    cands: list[dict] = []
    ml, kin = mode.get("ml", {}), mode.get("kinematic", {})
    if ml.get("verified", 0) >= 5 and kin.get("verified", 0) >= 5:
        ml_mae, kin_mae = ml.get("mae_km"), kin.get("mae_km")
        if ml_mae is not None and kin_mae is not None and (ml_mae > kin_mae + 2.0 or (kin_mae > 0 and ml_mae / kin_mae >= 1.35)):
            _add(cands, "ml_worse_than_kinematic", "warning", _confidence(ml["verified"] + kin["verified"], True), {"ml": ml, "kinematic": kin})
        if ml_mae is not None and kin_mae is not None and (kin_mae > ml_mae + 2.0 or (ml_mae > 0 and kin_mae / ml_mae >= 1.35)):
            _add(cands, "kinematic_worse_than_ml", "warning", _confidence(ml["verified"] + kin["verified"], True), {"ml": ml, "kinematic": kin})

    dir_vals = [_f(r.get("direction_error_deg")) for r in verified_short]; dir_vals = [v for v in dir_vals if v is not None]
    spd_vals = [_f(r.get("speed_error_kmh")) for r in verified_short]; spd_vals = [v for v in spd_vals if v is not None]
    dir_med, dir_p90 = (_pct(dir_vals, 50), _pct(dir_vals, 90))
    spd_med, spd_p90 = (_pct(spd_vals, 50), _pct(spd_vals, 90))
    direction_dominates = (dir_med is not None and dir_med >= 45) or (dir_p90 is not None and dir_p90 >= 100)
    base["direction_diagnosis"] = {"samples": len(dir_vals), "median_direction_error_deg": dir_med, "p90_direction_error_deg": dir_p90}
    base["speed_diagnosis"] = {"samples": len(spd_vals), "median_speed_error_kmh": spd_med, "p90_speed_error_kmh": spd_p90}
    if direction_dominates:
        _add(cands, "direction_error_dominates", "warning", _confidence(len(dir_vals), True), base["direction_diagnosis"])
    if spd_med is not None and spd_med >= 20 and not direction_dominates:
        _add(cands, "speed_error_dominates", "warning", _confidence(len(spd_vals), True), base["speed_diagnosis"])

    nearest = match.get("nearest", {})
    refs = [v for k, v in match.items() if k in ("id", "cell_id") and v.get("mae_km") is not None]
    best_ref = min((v["mae_km"] for v in refs), default=None)
    if nearest.get("verified", 0) >= 5 and best_ref is not None and nearest.get("mae_km") is not None and (nearest["mae_km"] > best_ref + 2.0 or nearest["mae_km"] >= best_ref * 1.5):
        _add(cands, "nearest_match_problem", "warning", _confidence(nearest["verified"], True), {"nearest": nearest, "best_id_or_cell_id_mae_km": best_ref})
    nearest_count = nearest.get("verified", 0); id_count = match.get("id", {}).get("verified", 0); cell_count = match.get("cell_id", {}).get("verified", 0)
    if (id_count < 5) and nearest_count >= 5 and cell_count > 0 and nearest_count / max(1, len(verified_short)) >= 0.5:
        _add(cands, "cell_id_matching_needed", "watch", 0.6, {"nearest_verified": nearest_count, "id_verified": id_count, "cell_id_verified": cell_count})

    no_target = sum(1 for r in short if r.get("no_target_frame") is True)
    total_short = len(short)
    history_rates = []
    for rec in history:
        for h in rec.get("horizons", []) or []:
            if (_f(h.get("horizon")) or 9999) <= SHORT_HORIZON_MAX_MIN:
                hs = int(h.get("samples", 0) or 0)
                hn = int(h.get("no_target_frame", 0) or 0)
                total_short += hs
                no_target += hn
                if hs:
                    history_rates.append(hn / hs)
    no_target_rate = max([no_target / total_short if total_short else 0.0] + history_rates)
    base["coverage_diagnosis"] = {"short_samples_total": total_short, "no_target_frame": no_target, "no_target_frame_rate": round(no_target_rate, 4)}
    if total_short and no_target_rate >= 0.3:
        _add(cands, "coverage_limited", "warning", _confidence(total_short, True), base["coverage_diagnosis"])

    err_stats = _stats(verified_short)
    if err_stats.get("verified", 0) and err_stats.get("p90_km") is not None and err_stats.get("median_km") and err_stats["p90_km"] >= 2.5 * err_stats["median_km"]:
        _add(cands, "outlier_dominated", "watch", _confidence(err_stats["verified"]), err_stats)
    if len(verified_short) < 10:
        _add(cands, "low_sample_count", "watch", 0.3, {"verified_short": len(verified_short)})

    health_path = details_path.parent / "motion_pipeline_health.json"
    try:
        health = json.loads(health_path.read_text(encoding="utf-8"))
    except Exception:
        health = {}
    short_mae = err_stats.get("mae_km")
    speed_plausible = bool(health.get("median_forecast_speed_kmh_by_horizon"))
    if health.get("pysteps_import_ok") is True and health.get("pysteps_lucaskanade_ok") is True and (health.get("of_available_pct") or 0) >= 50 and speed_plausible and short_mae is not None and short_mae > TARGET_MAE_KM:
        _add(cands, "motion_pipeline_ok_but_accuracy_bad", "warning", _confidence(len(verified_short)), {"short_mae_km": short_mae, "of_available_pct": health.get("of_available_pct")})

    sev_order = {"ok": 0, "watch": 1, "warning": 2, "critical": 3}
    drift_active = short_mae is not None and short_mae > TARGET_MAE_KM
    severity = "ok"
    if cands:
        severity = max((c["severity"] for c in cands), key=lambda s: sev_order[s])
    if any(c["code"] == "low_sample_count" for c in cands) and len(cands) == 1:
        severity = "watch"
    elif drift_active and any(c["confidence"] >= 0.75 and c["severity"] == "warning" for c in cands):
        severity = "critical"
    base["status"] = "ok" if len(verified_short) >= 10 else "insufficient_data"
    base["severity"] = severity
    base["root_cause_candidates"] = sorted(cands, key=lambda c: ({"critical": 3, "warning": 2, "watch": 1, "ok": 0}[c["severity"]], c["confidence"]), reverse=True)
    base["primary_findings"] = [FINDINGS[c["code"]] for c in base["root_cause_candidates"][:5]]
    base["recommendations"] = list(dict.fromkeys([c["recommendation"] for c in base["root_cause_candidates"]]))
    base["worst_forecasts"] = sorted(verified, key=lambda r: _f(r.get("forecast_error_km")) or 0, reverse=True)[:10]
    return base


def write_forecast_error_diagnosis(diagnosis: dict, path: str | Path = DIAGNOSIS_FILE) -> None:
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(diagnosis, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def load_latest_forecast_error_diagnosis(path: str | Path = DIAGNOSIS_FILE) -> dict:
    path = Path(path)
    if not path.exists():
        return {"status": "missing", "severity": "watch", "primary_findings": [], "recommendations": ["B211 muss zuerst Daten sammeln."], "root_cause_candidates": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"status": "missing"}
    except Exception as exc:
        return {"status": "missing", "severity": "watch", "message": str(exc), "primary_findings": [], "recommendations": [], "root_cause_candidates": []}
