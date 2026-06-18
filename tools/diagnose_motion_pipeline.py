#!/usr/bin/env python3
"""Offline-Diagnose für Optical-Flow-/Forecast-Pipeline."""
from __future__ import annotations

import argparse, glob, json, math, os, statistics, sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

HORIZONS = (10, 20, 30, 40, 60)


def _haversine_km(lat1, lon1, lat2, lon2):
    try:
        lat1, lon1, lat2, lon2 = map(float, (lat1, lon1, lat2, lon2))
        r = 6371.0
        dlat = math.radians(lat2 - lat1); dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
        return 2*r*math.asin(math.sqrt(max(0.0, min(1.0, a))))
    except Exception:
        return None


def _parse_ts(path: Path):
    try:
        return datetime.strptime(path.stem, "%Y-%m-%d_%H-%M-%S").replace(tzinfo=timezone.utc)
    except Exception:
        try:
            return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except Exception:
            return None


def _pysteps_check():
    import_ok = False; lk_ok = False; err = None
    try:
        import numpy as np  # noqa
        import pysteps  # noqa
        import_ok = True
        from pysteps.motion.lucaskanade import dense_lucaskanade
        arr = np.zeros((2, 48, 48), dtype=np.float32)
        arr[0, 15:26, 14:25] = 1.0; arr[1, 15:26, 18:29] = 1.0
        arr = np.where(arr < 0.01, np.nan, arr)
        uv = dense_lucaskanade(arr)
        lk_ok = tuple(getattr(uv, "shape", ())) == (2, 48, 48)
    except Exception as exc:
        err = str(exc)
    return import_ok, lk_ok, err


def _load_json(path: Path, warnings: Counter):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        warnings["bad_object_json"] += 1
        return []



def _latest_accuracy_attribution(eval_dir: Path, warnings: Counter, recommendations: list) -> dict:
    details = eval_dir / "forecast_error_details.jsonl"
    history = eval_dir / "accuracy_history.jsonl"
    if not details.exists():
        warnings["forecast_error_details_missing"] = True
        recommendations.append("Forecast error detail logging is not available yet.")
    latest = {}
    try:
        if history.exists():
            for line in history.read_text(encoding="utf-8").splitlines():
                try:
                    rec = json.loads(line)
                    if isinstance(rec, dict): latest = rec
                except Exception: pass
    except Exception:
        warnings["accuracy_history_read_error"] += 1
    return {
        "latest_timestamp_utc": latest.get("timestamp_utc"),
        "breakdown_by_forecast_mode": latest.get("breakdown_by_forecast_mode", {}),
        "breakdown_by_kinematic_source": latest.get("breakdown_by_kinematic_source", {}),
        "breakdown_by_match_type": latest.get("breakdown_by_match_type", {}),
        "direction_stats_by_horizon": latest.get("direction_stats_by_horizon", {}),
        "speed_stats_by_horizon": latest.get("speed_stats_by_horizon", {}),
        "worst_forecasts": latest.get("worst_forecasts", []),
        "diagnosis": latest.get("diagnosis", []),
    }

def build_health(hours: int = 24, base_dir: str | Path = "."):
    base = Path(base_dir)
    eval_dir = base / "train_data" / "evaluation"
    obj_dir = base / "train_data" / "objects"
    now = datetime.now(timezone.utc); cutoff = now - timedelta(hours=hours)
    warnings = Counter()
    pysteps_import_ok, pysteps_lucaskanade_ok, pysteps_error = _pysteps_check()

    files = []
    for raw in glob.glob(str(obj_dir / "*.json")):
        p = Path(raw); ts = _parse_ts(p)
        if ts and ts >= cutoff:
            files.append(p)
    files.sort()

    objects_total = of_available_count = zero_motion = 0
    of_speeds = []; forecast_modes = Counter(); kin_sources = Counter()
    zero_by_h = Counter(); count_by_h = Counter(); disp_by_h = defaultdict(list); speed_by_h = defaultdict(list)

    for path in files:
        for obj in _load_json(path, warnings):
            if not isinstance(obj, dict):
                continue
            objects_total += 1
            if int(obj.get("of_available", 0) or 0) == 1:
                of_available_count += 1
            try: of_speeds.append(float(obj.get("of_speed", 0.0) or 0.0))
            except Exception: pass
            forecast_modes[str(obj.get("forecast_mode") or "unknown")] += 1
            kin_sources[str(obj.get("kinematic_source") or "unknown")] += 1
            try:
                live_speed = float(obj.get("kinematic_speed_kmh", obj.get("speed_kmh", 0.0)) or 0.0)
            except Exception:
                live_speed = 0.0
            vx0 = float(obj.get("kinematic_vx", obj.get("vx", 0.0)) or 0.0); vy0 = float(obj.get("kinematic_vy", obj.get("vy", 0.0)) or 0.0)
            if live_speed < 5.0 or math.hypot(vx0, vy0) < 0.01:
                zero_motion += 1
            origin_lat = obj.get("origin_lat", obj.get("lat")); origin_lon = obj.get("origin_lon", obj.get("lon"))
            for h in HORIZONS:
                flat = obj.get(f"forecast_lat_{h}"); flon = obj.get(f"forecast_lon_{h}")
                if None in (origin_lat, origin_lon, flat, flon):
                    warnings[f"missing_forecast_{h}"] += 1; continue
                d = _haversine_km(origin_lat, origin_lon, flat, flon)
                if d is None:
                    warnings[f"invalid_forecast_{h}"] += 1; continue
                count_by_h[str(h)] += 1; disp_by_h[str(h)].append(d); speed_by_h[str(h)].append(d/(h/60.0))
                if d < 0.5: zero_by_h[str(h)] += 1

    latest_drift = {}
    try:
        latest_drift = json.loads((eval_dir / "drift_status.json").read_text(encoding="utf-8"))
    except Exception:
        warnings["missing_or_bad_drift_status"] += 1

    def pct(n, d): return round(n / d * 100.0, 2) if d else 0.0
    med_disp = {h: round(statistics.median(v), 3) for h, v in disp_by_h.items() if v}
    med_speed = {h: round(statistics.median(v), 2) for h, v in speed_by_h.items() if v}
    zero_pct = {h: pct(zero_by_h[h], count_by_h[h]) for h in [str(x) for x in HORIZONS]}

    diagnosis = []; recommendations = []
    accuracy_attribution = _latest_accuracy_attribution(eval_dir, warnings, recommendations)
    if not pysteps_import_ok:
        diagnosis.append("pysteps_import_ok=false: pySTEPS ist nicht importierbar.")
        recommendations.append("pySTEPS im venv installieren/aktualisieren.")
    if pysteps_import_ok and not pysteps_lucaskanade_ok:
        diagnosis.append("pysteps_lucaskanade_ok=false: dense_lucaskanade Funktionstest fehlgeschlagen.")
    if objects_total and pct(of_available_count, objects_total) < 5.0:
        diagnosis.append("Optical Flow inactive: of_available ist nahezu 0.")
    if med_speed and statistics.median(med_speed.values()) < 5.0:
        diagnosis.append("Forecast displacement near zero: mediane Forecast-Geschwindigkeit ist sehr niedrig.")
    if not diagnosis:
        diagnosis.append("Keine offensichtliche Motion-Pipeline-Störung im geprüften Fenster.")
    if any("Optical Flow inactive" in d for d in diagnosis):
        recommendations.append("install.sh erneut ausführen und pySTEPS Lucas-Kanade Funktionstest prüfen.")
    if any("Forecast displacement near zero" in d for d in diagnosis):
        recommendations.append("kinematic_source-Verteilung prüfen; kalman_only-Anteil reduzieren, History/EWMA und Optical Flow prüfen.")

    return {
        "checked_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"), "hours": hours,
        "pysteps_import_ok": pysteps_import_ok, "pysteps_lucaskanade_ok": pysteps_lucaskanade_ok,
        "pysteps_error": pysteps_error, "object_files": len(files), "objects_total": objects_total,
        "of_available_count": of_available_count, "of_available_pct": pct(of_available_count, objects_total),
        "of_speed_median_px_frame": round(statistics.median(of_speeds), 4) if of_speeds else 0.0,
        "forecast_mode_counts": dict(forecast_modes), "kinematic_source_counts": dict(kin_sources),
        "zero_motion_object_pct": pct(zero_motion, objects_total),
        "zero_forecast_pct_by_horizon": zero_pct,
        "median_forecast_displacement_km_by_horizon": med_disp,
        "median_forecast_speed_kmh_by_horizon": med_speed,
        "forecast_sample_count_by_horizon": dict(count_by_h), "warnings": dict(warnings),
        "latest_drift_status": latest_drift, "accuracy_attribution": accuracy_attribution,
        "diagnosis": diagnosis, "recommendations": recommendations,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--hours", type=int, default=24); ap.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)
    health = build_health(ns.hours)
    out = Path("train_data/evaluation/motion_pipeline_health.json"); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(health, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(health, indent=2 if ns.json else None, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
