#!/usr/bin/env python3
"""Offline-Forecast-Qualitätsdiagnose für den 24h-Debug-Export."""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from config import (
        DIAGNOSIS_MIN_VERIFIED_FORECASTS as _DIAG_MIN_VERIFIED,
        DIAGNOSIS_MAX_MISSING_TARGET_RATIO as _DIAG_MAX_MISSING_RATIO,
    )
except Exception:
    _DIAG_MIN_VERIFIED = 30
    _DIAG_MAX_MISSING_RATIO = 0.4
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    from config import SAVE_PATHS
except Exception:  # pragma: no cover
    SAVE_PATHS = {"evaluation": "train_data/evaluation", "objects": "train_data/objects", "radar": "train_data/radar"}

from export_diagnosis import ERROR_NAME, LATEST_NAME, utc_now_z


def _parse_ts(v: Any):
    if not v:
        return None
    raw = str(v).strip()
    for value in (raw, raw.replace("Z", "+00:00")):
        try:
            return datetime.fromisoformat(value)
        except Exception:
            pass
    for fmt in ("%Y-%m-%d_%H-%M-%S", "%Y%m%d_%H%M%S"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return None


def _f(v: Any):
    try:
        if v is None:
            return None
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _resolve_save_path(base_dir: Path, key: str, default: str) -> Path:
    raw = Path(SAVE_PATHS.get(key, default))
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
        ts = next((_parse_ts(rec.get(k)) for k in ("verified_at_utc", "target_timestamp_utc", "forecast_created_at_utc", "timestamp_utc", "created_at_utc", "ir_first_seen", "radar_first_confirmed") if _parse_ts(rec.get(k))), None)
        if ts is None or ts >= cutoff:
            rows.append(rec)
    return rows



def _read_accuracy_history_horizons(path: Path, hours: int) -> list[dict]:
    """Liest accuracy_history.jsonl und gibt flache Liste von Horizont-Records zurück.

    B257: Unterstützt sowohl neues verschachteltes Format
    {"horizons": [{"horizon": 10, "mae_km": ...}]}
    als auch altes Flat-Format {"horizon": 10, "mae_km": ...}.
    """
    rows = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    if not path.exists():
        return rows
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if not isinstance(rec, dict):
                continue
            ts = _parse_ts(rec.get("timestamp_utc"))
            if ts is not None and ts < cutoff:
                continue
            # B257: neues verschachteltes Format bevorzugen
            nested = rec.get("horizons")
            if isinstance(nested, list):
                for h_entry in nested:
                    if isinstance(h_entry, dict) and h_entry.get("horizon") is not None:
                        # Kontext-Felder aus dem Parent-Eintrag übernehmen
                        merged = dict(rec)
                        merged.update(h_entry)
                        rows.append(merged)
            else:
                # Altes Flat-Format: Top-Level-horizon vorhanden
                if rec.get("horizon") is not None:
                    rows.append(rec)
    return rows


def _model_usage_from_accuracy_history(rows: list[dict]) -> dict:
    if not rows:
        return {"status": "not_available"}

    # B294: Pro Horizont die JÜNGSTE Zeile mit samples>0 behalten, statt bei
    # jeder Zeile zu überschreiben (sonst gewinnt die letzte, evtl. leere
    # 0-Sample-Zeile aus einer Schönwetter-Flaute). total_samples wird
    # konsistent aus genau diesen ausgewählten Einträgen summiert.
    def _row_ts(r):
        return _parse_ts(r.get("timestamp_utc")) or datetime.min.replace(tzinfo=timezone.utc)

    best_by_horizon: dict[str, dict] = {}
    best_ts_by_horizon: dict[str, datetime] = {}
    for row in rows:
        horizon = row.get("horizon")
        if horizon is None:
            continue
        samples = int(_f(row.get("samples")) or 0)
        if samples <= 0:
            continue
        hk = str(horizon)
        ts = _row_ts(row)
        if hk not in best_ts_by_horizon or ts >= best_ts_by_horizon[hk]:
            best_ts_by_horizon[hk] = ts
            best_by_horizon[hk] = {
                "samples": samples,
                "mae_km": _f(row.get("mae_km")),
                "hit_rate": _f(row.get("hit_rate")),
            }

    if not best_by_horizon:
        return {"status": "not_available"}

    total_samples = sum(item["samples"] for item in best_by_horizon.values())
    return {
        "status": "available",
        "horizon_count": len(best_by_horizon),
        "total_samples": total_samples,
        "by_horizon": best_by_horizon,
    }

def _ratio(rows, pred):
    return round(sum(1 for r in rows if pred(r)) / len(rows), 4) if rows else None


def _feature_stats(rows: list[dict], names: list[str]) -> dict:
    out = {}
    for name in names:
        vals = [r.get(name) for r in rows if name in r]
        out[name] = {
            "present_samples": len(vals),
            "missing_ratio": round(1 - (len(vals) / len(rows)), 4) if rows else None,
            "null_ratio": round(sum(v in (None, "") for v in vals) / len(vals), 4) if vals else None,
            "zero_ratio": round(sum((_f(v) == 0.0) for v in vals) / len(vals), 4) if vals else None,
            "fallback_ratio": _ratio(rows, lambda r, n=name: bool(r.get(f"{n}_fallback") or r.get(f"{n}_is_fallback") or r.get("fallback"))),
        }
    return out


def _id_matching(rows: list[dict], outliers: list[dict]) -> dict:
    suspect_terms = ("switch", "reid", "merge", "split", "ghost", "nearest", "lost")
    suspect = []
    for r in rows:
        text = " ".join(str(r.get(k, "")) for k in ("match_type", "lineage_status", "tracking_status", "event", "forecast_reject_reason")).lower()
        if any(t in text for t in suspect_terms):
            suspect.append(r)
    outlier_ids = {str(r.get("cell_id") or r.get("object_id") or "") for r in outliers}
    return {
        "suspect_count": len(suspect),
        "affected_cell_ids": sorted({str(r.get("cell_id") or r.get("object_id")) for r in suspect if r.get("cell_id") or r.get("object_id")})[:50],
        "outlier_related_count": sum(1 for r in suspect if str(r.get("cell_id") or r.get("object_id") or "") in outlier_ids),
        "example_events": [{k: r.get(k) for k in ("forecast_created_at_utc", "target_timestamp_utc", "horizon_min", "cell_id", "object_id", "match_type", "lineage_status")} for r in suspect[:10]],
    }


def build_diagnosis(base_dir: Path, hours: int, evaluation_dir: Path | None = None) -> dict:
    ev = evaluation_dir or _resolve_save_path(base_dir, "evaluation", "train_data/evaluation")
    details = _read_jsonl(ev / "forecast_error_details.jsonl", hours)
    accuracy_rows = _read_accuracy_history_horizons(ev / "accuracy_history.jsonl", hours)
    verified = [r for r in details if _f(r.get("forecast_error_km")) is not None]
    outliers = sorted(verified, key=lambda r: _f(r.get("forecast_error_km")) or 0, reverse=True)[:10]
    px_geo = []
    for r in verified:
        km = _f(r.get("forecast_error_km"))
        dx = _f(r.get("forecast_error_x_px")); dy = _f(r.get("forecast_error_y_px"))
        px = math.hypot(dx or 0, dy or 0) if dx is not None or dy is not None else None
        if km is not None and px is not None:
            km_per_px = km / px if px > 0 else None
            if (px == 0 and km > 1) or (km_per_px is not None and (km_per_px < 0.05 or km_per_px > 5)):
                px_geo.append({"cell_id": r.get("cell_id") or r.get("object_id"), "error_km": km, "pixel_error_px": round(px, 3), "km_per_px": round(km_per_px, 4) if km_per_px else None})
    # B257: Feldnamen exakt an die von accuracy_tracker._detail_record (B249) geschriebenen
    # Spalten koppeln. Legacy-Namen (wind_speed/temperature/grosswetterlage/valley_*_score)
    # erzeugten sonst falsche "100 % missing"-Befunde und verdeckten echte Defizite.
    terrain = ["dem_elevation_m", "dem_slope_toward_cell", "dem_barrier_ahead", "valley_alignment", "terrain_blocking_score", "orographic_lift_score"]
    # B299: dem_slope_barrier_status-Verteilung separat ausweisen, damit
    # "no_movement_vector" (physikalisch erwartbar) nicht mit "dem_unavailable"
    # (echter Datenausfall) verwechselt wird.
    status_values = [r.get("dem_slope_barrier_status") for r in details if r.get("dem_slope_barrier_status")]
    dem_slope_barrier_status_breakdown = {
        status: status_values.count(status) for status in ("computed", "no_movement_vector", "dem_unavailable")
    } if status_values else None
    weather = ["wind_speed_700hPa", "wind_speed_500hPa", "wind_dir_cos", "wind_dir_sin", "cape", "arome_li", "arome_t2m", "nowcast_rr_mm15", "lightning_count_10km"]
    lineage_dir = _resolve_save_path(base_dir, "cell_lineage", "train_data/cell_lineage")
    label_rows = _read_jsonl(lineage_dir / "ir_lead_time_labels.jsonl", hours)
    ir_rows = [r for r in details if r.get("ir_first_seen_utc") or r.get("radar_first_seen_utc") or r.get("ir_lead_time_min") is not None]
    ir_rows.extend(label_rows)
    leads = []
    seen = set()
    no_lead = 0
    for r in ir_rows:
        cid = r.get("cell_id") or r.get("object_id")
        ir_seen = r.get("ir_first_seen_utc") or r.get("ir_first_seen")
        radar_seen = r.get("radar_first_seen_utc") or r.get("radar_first_confirmed")
        key = (cid, ir_seen, radar_seen)
        if key in seen:
            continue
        seen.add(key)
        lead = _f(r.get("ir_lead_time_min") if r.get("ir_lead_time_min") is not None else r.get("lead_time_min"))
        if lead is None:
            ir = _parse_ts(ir_seen); radar = _parse_ts(radar_seen)
            if ir and radar:
                lead = (radar - ir).total_seconds() / 60.0
        if lead is None or lead <= 0:
            no_lead += 1
        else:
            leads.append(lead)
    findings = []
    if outliers:
        findings.append(f"Größter Forecast-Ausreißer: {(_f(outliers[0].get('forecast_error_km')) or 0):.2f} km.")
    if px_geo:
        findings.append(f"{len(px_geo)} Pixel-vs-Geo-Verdachtsfälle gefunden.")
    missing_target = sum(1 for r in details if r.get("no_target_frame") is True or str(r.get("match_type") or "").lower() == "no_target_frame")
    if missing_target:
        findings.append(f"{missing_target} Forecasts ohne Ziel-Radarframe.")
    recs = []
    if px_geo:
        recs.append("Pixel→Geo/BBOX/Crop-Upscale-Kette anhand der Verdachtsfälle prüfen.")
    if missing_target:
        recs.append("Radarframe-Coverage und Verifikationstoleranz im Exportfenster prüfen.")
    # B293: Status ehrlich aus Stichprobengröße + Coverage ableiten statt fest "ok".
    _missing_ratio = round(missing_target / len(details), 4) if details else None
    if len(verified) < _DIAG_MIN_VERIFIED or (_missing_ratio is not None and _missing_ratio > _DIAG_MAX_MISSING_RATIO):
        _status = "insufficient_data"
        findings.insert(0, (
            f"Geringe Aussagekraft: nur {len(verified)} verifizierte Forecasts"
            f"{f', Missing-Target-Ratio {_missing_ratio}' if _missing_ratio is not None else ''}."
        ))
        if "Datenlage vor Interpretation prüfen (Flaute/geringe Coverage)." not in recs:
            recs.insert(0, "Datenlage vor Interpretation prüfen (Flaute/geringe Coverage).")
    else:
        _status = "ok"
    return {
        "schema": 1,
        "status": _status,
        "checked_at_utc": utc_now_z(),
        "hours": hours,
        "sample_counts": {"forecast_error_details": len(details), "verified_forecasts": len(verified), "ir_lead_time_labels": len(label_rows)},
        "forecast_outliers": [{"cell_id": r.get("cell_id") or r.get("object_id"), "error_km": _f(r.get("forecast_error_km")), "forecast_position": {"lat": _f(r.get("forecast_lat")), "lon": _f(r.get("forecast_lon"))}, "actual_position": {"lat": _f(r.get("actual_lat")), "lon": _f(r.get("actual_lon"))}, "horizon_min": _f(r.get("horizon_min")), "forecast_created_at_utc": r.get("forecast_created_at_utc")} for r in outliers],
        "pixel_geo_consistency": {"suspect_count": len(px_geo), "examples": px_geo[:10]},
        "id_matching": _id_matching(details, outliers),
        "missing_target_frames": {"count": missing_target, "ratio": round(missing_target / len(details), 4) if details else None},
        "dem_orography": _feature_stats(details, terrain),
        "dem_slope_barrier_status_breakdown": dem_slope_barrier_status_breakdown,
        "weather_features": _feature_stats(details, weather),
        "ir_precursors": {"median_lead_time_min": round(statistics.median(leads), 2) if leads else None, "matched_count": len(leads), "no_lead_count": no_lead},
        "model_usage": _model_usage_from_accuracy_history(accuracy_rows),
        "important_findings": findings,
        "recommendations": recs or ["Keine akuten Diagnoseempfehlungen aus lokalen 24h-Daten ableitbar."],
    }


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
