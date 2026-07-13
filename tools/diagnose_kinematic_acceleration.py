#!/usr/bin/env python3
"""B349: Offline-Validierung der Beschleunigungs-Root-Cause-Hypothese für den
24h-Debug-Export.

Nutzt den B348-Diagnose-Proxy (kinematic_accel_proxy_kmh) aus
forecast_error_details.jsonl, um zu prüfen, ob beschleunigende Zellen einen
systematisch größeren (signierten) Geschwindigkeitsfehler haben als stabile
Zellen — unabhängig davon, ob KINEMATIC_ACCELERATION_ENABLED (B307) aktiv
ist. Reine Beobachtung/Statistik, kein Verhaltens-Fix.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    from config import SAVE_PATHS
except Exception:  # pragma: no cover
    SAVE_PATHS = {"evaluation": "train_data/evaluation"}

from export_diagnosis import utc_now_z

LATEST_NAME = "kinematic_acceleration_validation_latest.json"
ERROR_NAME = "kinematic_acceleration_validation_error.json"

# B349: Bucket-Grenzen fuer den Beschleunigungs-Proxy (km/h Delta zwischen den
# letzten zwei Intervallgeschwindigkeiten). Bewusst symmetrisch und moderat,
# damit auch bei wenig Daten alle Buckets eine Chance auf Samples haben.
_ACCEL_STRONG_THRESHOLD_KMH = 10.0
_ACCEL_MODERATE_THRESHOLD_KMH = 3.0
_MIN_SAMPLES_FOR_CONCLUSION = 20


def _parse_ts(v: Any):
    if not v:
        return None
    raw = str(v).strip()
    for value in (raw, raw.replace("Z", "+00:00")):
        try:
            return datetime.fromisoformat(value)
        except Exception:
            pass
    return None


def _f(v: Any) -> float | None:
    try:
        if v is None:
            return None
        x = float(v)
        return x if x == x and abs(x) != float("inf") else None
    except Exception:
        return None


def _resolve_save_path(base_dir: Path, key: str, default: str, save_paths: dict | None = None) -> Path:
    paths = save_paths or SAVE_PATHS
    raw = Path(paths.get(key, default))
    return raw if raw.is_absolute() else base_dir / raw


def _read_jsonl(path: Path, hours: int) -> list[dict]:
    if not path.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if not isinstance(rec, dict):
            continue
        ts = next(
            (_parse_ts(rec.get(k)) for k in ("verified_at_utc", "target_timestamp_utc", "forecast_created_at_utc") if _parse_ts(rec.get(k))),
            None,
        )
        if ts is not None and ts >= cutoff:
            rows.append(rec)
    return rows


def _accel_bucket(proxy_kmh: float) -> str:
    if proxy_kmh >= _ACCEL_STRONG_THRESHOLD_KMH:
        return "accelerating_strong"
    if proxy_kmh >= _ACCEL_MODERATE_THRESHOLD_KMH:
        return "accelerating_moderate"
    if proxy_kmh <= -_ACCEL_STRONG_THRESHOLD_KMH:
        return "decelerating_strong"
    if proxy_kmh <= -_ACCEL_MODERATE_THRESHOLD_KMH:
        return "decelerating_moderate"
    return "stable"


def _pearson_r(xs: list[float], ys: list[float]) -> float | None:
    """Reine Python-Implementierung (kein numpy-Import fuer dieses kleine
    Offline-Skript), analog zum Stil der uebrigen tools/diagnose_*-Skripte."""
    n = len(xs)
    if n < 2:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x <= 0.0 or var_y <= 0.0:
        return None
    return cov / ((var_x ** 0.5) * (var_y ** 0.5))


def _bucket_stats(rows: list[dict]) -> dict:
    signed_errors = [r["_signed_speed_error_kmh"] for r in rows]
    return {
        "samples": len(rows),
        "mean_signed_speed_error_kmh": round(statistics.mean(signed_errors), 3) if signed_errors else None,
        "median_signed_speed_error_kmh": round(statistics.median(signed_errors), 3) if signed_errors else None,
        "mean_forecast_error_km": round(statistics.mean([r["_error_km"] for r in rows if r.get("_error_km") is not None]), 3)
        if any(r.get("_error_km") is not None for r in rows) else None,
    }


def build_diagnosis(base_dir: Path, hours: int, evaluation_dir: Path | None = None) -> dict:
    ev = evaluation_dir or _resolve_save_path(base_dir, "evaluation", "train_data/evaluation")
    details = _read_jsonl(ev / "forecast_error_details.jsonl", hours)

    candidates = []
    for r in details:
        if str(r.get("forecast_mode") or "") != "kinematic_fallback":
            continue
        proxy = _f(r.get("kinematic_accel_proxy_kmh"))
        fc_speed = _f(r.get("forecast_speed_kmh"))
        ac_speed = _f(r.get("actual_speed_kmh"))
        if proxy is None or fc_speed is None or ac_speed is None:
            continue
        rec = dict(r)
        rec["_signed_speed_error_kmh"] = ac_speed - fc_speed  # positiv = Forecast zu langsam
        rec["_error_km"] = _f(r.get("forecast_error_km"))
        rec["_accel_proxy"] = proxy
        candidates.append(rec)

    short_horizon = [r for r in candidates if (_f(r.get("horizon_min")) or 9999) <= 30]

    by_bucket: dict[str, list[dict]] = {}
    for r in short_horizon:
        by_bucket.setdefault(_accel_bucket(r["_accel_proxy"]), []).append(r)
    bucket_order = ["decelerating_strong", "decelerating_moderate", "stable", "accelerating_moderate", "accelerating_strong"]
    bucket_stats = {b: _bucket_stats(by_bucket.get(b, [])) for b in bucket_order}

    applied_true = [r for r in short_horizon if bool(r.get("kinematic_acceleration_applied"))]
    applied_false = [r for r in short_horizon if not bool(r.get("kinematic_acceleration_applied"))]

    xs = [r["_accel_proxy"] for r in short_horizon]
    ys = [r["_signed_speed_error_kmh"] for r in short_horizon]
    correlation = _pearson_r(xs, ys)

    n_total = len(short_horizon)
    status = "ok" if n_total >= _MIN_SAMPLES_FOR_CONCLUSION else "insufficient_data"

    findings = []
    recommendations = []
    if status == "insufficient_data":
        findings.append(
            f"Zu wenige verifizierte kinematische Kurzhorizont-Forecasts mit Beschleunigungs-Proxy "
            f"({n_total} < {_MIN_SAMPLES_FOR_CONCLUSION}) — Aussage nicht belastbar."
        )
        recommendations.append(
            "Mehr Daten sammeln (B348 muss laengere Zeit aktiv sein) bevor eine "
            "Aktivierung von KINEMATIC_ACCELERATION_ENABLED anhand dieser Diagnose entschieden wird."
        )
    else:
        accel_bucket_n = bucket_stats["accelerating_strong"]["samples"] + bucket_stats["accelerating_moderate"]["samples"]
        stable_mean = bucket_stats["stable"]["mean_signed_speed_error_kmh"]
        accel_strong_mean = bucket_stats["accelerating_strong"]["mean_signed_speed_error_kmh"]
        if correlation is not None:
            findings.append(f"Pearson-Korrelation Beschleunigungs-Proxy vs. signierter Speed-Error: r={round(correlation, 3)}.")
        if accel_bucket_n >= 10 and stable_mean is not None and accel_strong_mean is not None:
            findings.append(
                f"Mittlerer signierter Speed-Error stabil={stable_mean} km/h vs. "
                f"stark beschleunigend={accel_strong_mean} km/h."
            )
        if correlation is not None and correlation > 0.2 and accel_bucket_n >= 10:
            findings.append(
                "Positive Korrelation und hoeherer Speed-Error bei beschleunigenden Zellen "
                "stuetzen die EWMA-Lag-Hypothese (B307)."
            )
            recommendations.append(
                "KINEMATIC_ACCELERATION_ENABLED testweise aktivieren (Admin-Panel/runtime_overrides.json) "
                "und diese Diagnose nach einigen Tagen erneut pruefen (mean_signed_speed_error_kmh in den "
                "accelerating_*-Buckets sollte sich Richtung 0 bewegen)."
            )
        elif correlation is not None:
            findings.append(
                "Kein hinreichend starker Zusammenhang zwischen Beschleunigungs-Proxy und Speed-Error "
                "in diesem Fenster gefunden — Hypothese nicht bestaetigt (aber auch nicht widerlegt, siehe Stichprobengroesse)."
            )
            recommendations.append("Vor Aktivierung von KINEMATIC_ACCELERATION_ENABLED weitere Fenster/Zeitraeume pruefen.")
        if not recommendations:
            recommendations.append("Keine Handlungsempfehlung aus diesem Fenster ableitbar.")

    return {
        "schema": 1,
        "status": status,
        "checked_at_utc": utc_now_z(),
        "hours": hours,
        "sample_counts": {
            "forecast_error_details_total": len(details),
            "kinematic_fallback_with_proxy": len(candidates),
            "short_horizon_le_30min": n_total,
            "acceleration_applied_true": len(applied_true),
            "acceleration_applied_false": len(applied_false),
        },
        "accel_buckets_short_horizon": bucket_stats,
        "correlation_accel_proxy_vs_signed_speed_error": round(correlation, 4) if correlation is not None else None,
        "important_findings": findings,
        "recommendations": recommendations,
    }


def run_before_export(*, hours: int = 24, base_dir: str | Path | None = None, save_paths: dict | None = None) -> dict:
    """B349: Robuster Vor-Export-Hook analog export_diagnosis.run_forecast_quality_diagnosis_before_export.
    Fehler werden persistiert, nicht weitergeworfen — der Export darf nicht blockiert werden."""
    base = Path(base_dir or ".").resolve()
    ev = _resolve_save_path(base, "evaluation", "train_data/evaluation", save_paths)
    ev.mkdir(parents=True, exist_ok=True)
    latest = ev / LATEST_NAME
    error = ev / ERROR_NAME
    try:
        diag = build_diagnosis(base, hours, ev)
        latest.write_text(json.dumps(diag, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        error.unlink(missing_ok=True)
        return {"status": "ok", "path": str(latest)}
    except Exception as exc:  # noqa: BLE001
        payload = {"status": "error", "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc(), "timestamp_utc": utc_now_z()}
        error.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        latest.unlink(missing_ok=True)
        return payload


def load_latest(*, base_dir: str | Path | None = None, save_paths: dict | None = None) -> dict:
    base = Path(base_dir or ".").resolve()
    ev = _resolve_save_path(base, "evaluation", "train_data/evaluation", save_paths)
    for name in (LATEST_NAME, ERROR_NAME):
        path = ev / name
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                data.setdefault("file", name)
                return data
            except Exception as exc:
                return {"status": "error", "error": str(exc), "file": name}
    return {"status": "missing", "file": None, "important_findings": [], "recommendations": ["Noch keine Beschleunigungs-Validierung ausgefuehrt (B348 muss zuerst Daten sammeln)."]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--base-dir", default=str(REPO))
    ap.add_argument("--evaluation-dir", default=None)
    args = ap.parse_args(argv)
    base = Path(args.base_dir).resolve()
    ev = Path(args.evaluation_dir) if args.evaluation_dir else _resolve_save_path(base, "evaluation", "train_data/evaluation")
    if not ev.is_absolute():
        ev = base / ev
    ev.mkdir(parents=True, exist_ok=True)
    try:
        diag = build_diagnosis(base, args.hours, ev)
        (ev / LATEST_NAME).write_text(json.dumps(diag, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        (ev / ERROR_NAME).unlink(missing_ok=True)
        print(str(ev / LATEST_NAME))
        return 0
    except Exception as exc:  # noqa: BLE001
        (ev / ERROR_NAME).write_text(json.dumps({"status": "error", "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc(), "timestamp_utc": utc_now_z()}, ensure_ascii=False, indent=2), encoding="utf-8")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
