"""Vorsichtige Verifikation ausstehender Hydro-Impact-Kandidaten.

Die Verifikation behauptet keine Kausalität zwischen einer Gewitterzelle und
Pegel-/Abflussanstiegen. Sie bewertet nur, ob gespeicherte Live-Rohdaten einen
plausiblen Zusammenhang im erwarteten Zeitfenster stützen, nicht stützen oder
ob die Lage wegen Datenlücken bzw. konkurrierender Zellen mehrdeutig bleibt.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

from config import SAVE_PATHS
from hydro_impact import IMPACT_DIR, NETWORK_INDEX_PATH, load_pending_hydro_impacts, save_hydro_impact_state

_HYDRO_BASE = Path(SAVE_PATHS.get("hydro", "train_data/hydro/live/"))
HYDRO_LIVE_DIR = Path(os.environ.get("HYDRO_LIVE_DIR", str(_HYDRO_BASE)))
HYDRO_VERIFICATION_PATH = Path(
    os.environ.get("HYDRO_VERIFICATION_PATH", str(IMPACT_DIR / "hydro_verifications.jsonl"))
)
HYDRO_VERIFICATION_SUMMARY_PATH = Path(
    os.environ.get("HYDRO_VERIFICATION_SUMMARY_PATH", str(IMPACT_DIR / "hydro_verification_summary.json"))
)
HYDRO_DEFAULT_LAG_MIN = [
    int(v.strip()) for v in os.environ.get("HYDRO_DEFAULT_LAG_MIN", "20,180").split(",")[:2]
]
HYDRO_EXTRA_WINDOWS_MIN = [10, 20, 30, 40, 60, 120, 180]
MIN_DELTA_Q_M3S = float(os.environ.get("HYDRO_VERIFY_MIN_DELTA_Q_M3S", "0.2"))
MIN_DELTA_W_CM = float(os.environ.get("HYDRO_VERIFY_MIN_DELTA_W_CM", "5"))
MIN_RELATIVE_DELTA_PCT = float(os.environ.get("HYDRO_VERIFY_MIN_RELATIVE_DELTA_PCT", "10"))
MAX_MEASUREMENT_GAP_MIN = int(os.environ.get("HYDRO_VERIFY_MAX_GAP_MIN", "90"))


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    text = str(value)
    for fmt in ("%Y-%m-%d_%H-%M-%S", "%Y%m%d_%H%M%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _load_json(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _lag_window(event: dict[str, Any]) -> list[int]:
    network = _load_json(NETWORK_INDEX_PATH, {})
    station_cfg = network.get(str(event.get("station_id")), {}) if isinstance(network, dict) else {}
    raw = station_cfg.get("estimated_lag_min") or station_cfg.get("lag_min") or event.get("estimated_lag_min")
    if isinstance(raw, (int, float)):
        return [int(raw), int(raw)]
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        try:
            return [int(raw[0]), int(raw[1])]
        except (TypeError, ValueError):
            pass
    return list(HYDRO_DEFAULT_LAG_MIN)


def _event_time(event: dict[str, Any]) -> datetime | None:
    for key in ("created_at", "event_time", "timestamp", "measured_at"):
        parsed = _parse_time(event.get(key))
        if parsed:
            return parsed
    return None


def _iter_hydro_points(station_id: str) -> list[dict[str, Any]]:
    points: dict[datetime, dict[str, Any]] = {}
    for path in sorted(HYDRO_LIVE_DIR.glob("hydro_*.json")):
        data = _load_json(path, {})
        stations = data.get("stations", []) if isinstance(data, dict) else []
        snapshot_time = _parse_time(data.get("fetched_at") or data.get("created_at") or data.get("timestamp"))
        for station in stations:
            sid = str(station.get("station_id") or station.get("id") or station.get("peg_id") or "")
            if sid != str(station_id):
                continue
            measured_at = _parse_time(station.get("measured_at") or station.get("timestamp")) or snapshot_time
            if not measured_at:
                continue
            points[measured_at] = {
                "measured_at": measured_at,
                "q_m3s": _to_float(station.get("q_m3s") if "q_m3s" in station else station.get("q")),
                "w_cm": _to_float(station.get("w_cm") if "w_cm" in station else station.get("w")),
                "raw_status": station.get("raw_data_notice") or station.get("status") or data.get("raw_data_notice"),
            }
    return [points[t] for t in sorted(points)]


def compute_hydro_delta(station_id, start_time, window_min) -> dict:
    """Berechnet Pegel-/Abflussänderungen ab ``start_time`` für ein Minutenfenster."""
    start = _parse_time(start_time)
    if not start:
        return {"station_id": str(station_id), "status": "missing_start_time", "points": []}
    end = start + timedelta(minutes=int(window_min))
    all_points = _iter_hydro_points(str(station_id))
    before = [p for p in all_points if p["measured_at"] <= start]
    window = [p for p in all_points if start < p["measured_at"] <= end]
    base = before[-1] if before else None
    gaps = []
    seq = ([base] if base else []) + window
    for a, b in zip(seq, seq[1:]):
        gap = (b["measured_at"] - a["measured_at"]).total_seconds() / 60
        if gap > MAX_MEASUREMENT_GAP_MIN:
            gaps.append(round(gap, 1))
    q_vals = [p["q_m3s"] for p in window if p.get("q_m3s") is not None]
    w_vals = [p["w_cm"] for p in window if p.get("w_cm") is not None]
    q_before = base.get("q_m3s") if base else None
    w_before = base.get("w_cm") if base else None
    q_after = max(q_vals) if q_vals else None
    w_after = max(w_vals) if w_vals else None
    dq = (q_after - q_before) if q_after is not None and q_before is not None else None
    dw = (w_after - w_before) if w_after is not None and w_before is not None else None
    return {
        "station_id": str(station_id),
        "start_time": start.isoformat().replace("+00:00", "Z"),
        "window_min": int(window_min),
        "points": [{**p, "measured_at": p["measured_at"].isoformat().replace("+00:00", "Z")} for p in window],
        "raw_data_status": "gap" if gaps else ("missing" if not base or not window else "ok"),
        "measurement_gaps_min": gaps,
        "q_before_m3s": q_before,
        "q_after_max_m3s": q_after,
        "delta_q_m3s": dq,
        "relative_delta_q_pct": (dq / q_before * 100) if dq is not None and q_before not in (None, 0) else None,
        "w_before_cm": w_before,
        "w_after_max_cm": w_after,
        "delta_w_cm": dw,
        "relative_delta_w_pct": (dw / w_before * 100) if dw is not None and w_before not in (None, 0) else None,
    }


def _same_hydro_context(event: dict[str, Any], other: dict[str, Any]) -> bool:
    """Vergleicht Konkurrenz im selben fachlichen Hydro-Kontext."""
    if str(other.get("station_id")) != str(event.get("station_id")):
        return False
    event_catchment = event.get("catchment_id")
    other_catchment = other.get("catchment_id")
    if event_catchment is not None and other_catchment is not None:
        return str(event_catchment) == str(other_catchment)
    return True


def _response_windows_overlap(event: dict[str, Any], other: dict[str, Any]) -> bool:
    event_time = _event_time(event)
    other_time = _event_time(other)
    if not event_time or not other_time:
        return False
    event_lag = _lag_window(event)
    other_lag = _lag_window(other)
    event_start = event_time + timedelta(minutes=event_lag[0])
    event_end = event_time + timedelta(minutes=event_lag[1])
    other_start = other_time + timedelta(minutes=other_lag[0])
    other_end = other_time + timedelta(minutes=other_lag[1])
    return event_start <= other_end and other_start <= event_end


def _has_competitors(event: dict[str, Any], candidates: list[dict[str, Any]] | None = None) -> bool:
    cell_id = str(event.get("cell_id"))
    for other in (candidates if candidates is not None else load_pending_hydro_impacts()):
        if str(other.get("cell_id")) == cell_id:
            continue
        if _same_hydro_context(event, other) and _response_windows_overlap(event, other):
            return True
    return False


def classify_hydro_response(event, hydro_series, competing_candidates: list[dict[str, Any]] | None = None) -> dict:
    """Klassifiziert vorsichtig: plausibel bestätigt, nicht bestätigt oder mehrdeutig."""
    reason: list[str] = []
    if hydro_series.get("raw_data_status") in {"missing", "gap"}:
        reason.append("Hydro-Rohdaten fehlen oder enthalten eine relevante Messlücke")
        return {"status": "ambiguous", "confidence": "low", "interpretation": "uneindeutig wegen Messlücke / konkurrierender Zellen", "reason": reason}
    if _has_competitors(event, competing_candidates):
        reason.extend(["competing_cells_same_catchment", "Mehrere konkurrierende Zellen im Einzugsgebiet erkannt"])
        return {"status": "ambiguous", "confidence": "low", "interpretation": "uneindeutig wegen Messlücke / konkurrierender Zellen", "reason": reason}
    dq = hydro_series.get("delta_q_m3s")
    dw = hydro_series.get("delta_w_cm")
    rq = hydro_series.get("relative_delta_q_pct")
    rw = hydro_series.get("relative_delta_w_pct")
    q_hit = dq is not None and (dq >= MIN_DELTA_Q_M3S or (rq is not None and rq >= MIN_RELATIVE_DELTA_PCT))
    w_hit = dw is not None and (dw >= MIN_DELTA_W_CM or (rw is not None and rw >= MIN_RELATIVE_DELTA_PCT))
    if q_hit or w_hit:
        if q_hit:
            reason.append("Abflussanstieg im erwarteten Zeitfenster")
        if w_hit:
            reason.append("Pegelanstieg im erwarteten Zeitfenster")
        reason.append("Bewertung beschreibt nur einen plausiblen Zusammenhang, keine Kausalitätsbehauptung")
        confidence = "high" if q_hit and w_hit else "medium"
        return {"status": "confirmed", "confidence": confidence, "interpretation": "plausibler hydrologischer Zusammenhang", "reason": reason}
    reason.append("Kein relevanter Pegel- oder Abflussanstieg im erwarteten Zeitfenster")
    reason.append("Zusammenhang nicht bestätigt")
    return {"status": "rejected", "confidence": "medium", "interpretation": "kein belastbarer Zusammenhang ableitbar", "reason": reason}



def _already_verified_event_ids() -> set[str]:
    done: set[str] = set()
    try:
        from hydro_impact import _load_hydro_impact_state
        state_events = (_load_hydro_impact_state().get("events") or {})
        done.update(str(eid) for eid, row in state_events.items() if isinstance(row, dict) and row.get("status") in {"confirmed", "rejected", "ambiguous"})
    except Exception:
        pass
    if not HYDRO_VERIFICATION_PATH.exists():
        return done
    for line in HYDRO_VERIFICATION_PATH.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except Exception:
            continue
        if row.get("status") in {"confirmed", "rejected", "ambiguous"} and row.get("event_id"):
            done.add(str(row.get("event_id")))
    return done

def _update_event_status(result: dict[str, Any]) -> None:
    try:
        from hydro_impact import LATEST_IMPACTS_PATH
        paths = [LATEST_IMPACTS_PATH]
        event_id = str(result.get("event_id"))
        save_hydro_impact_state(event_id, {"status": result.get("status"), "verification": result, "confidence": result.get("confidence"), "verified_at": result.get("verified_at")})
        for path in paths:
            data = _load_json(path, [])
            if not isinstance(data, list):
                continue
            changed = False
            for event in data:
                if isinstance(event, dict) and str(event.get("event_id")) == event_id:
                    event["status"] = result.get("status")
                    event["verification"] = result
                    event["confidence"] = result.get("confidence", event.get("confidence"))
                    changed = True
            if changed:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:
        pass

def save_hydro_verification(result) -> None:
    HYDRO_VERIFICATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    with HYDRO_VERIFICATION_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")


def verify_pending_hydro_impacts(now: datetime | None = None) -> list[dict]:
    current = _parse_time(now) or datetime.now(timezone.utc)
    results = []
    done = _already_verified_event_ids()
    pending_events = load_pending_hydro_impacts()
    for event in pending_events:
        if str(event.get("event_id")) in done:
            continue
        event_at = _event_time(event)
        lag = _lag_window(event)
        if not event_at:
            observed = compute_hydro_delta(event.get("station_id"), current, 1)
            classified = {"status": "ambiguous", "confidence": "low", "interpretation": "uneindeutig wegen fehlender Ereigniszeit", "reason": ["Ereigniszeit fehlt"]}
        elif current < event_at + timedelta(minutes=lag[1]):
            observed = {}
            classified = {"status": "pending", "confidence": "low", "interpretation": "Verifikation steht noch aus", "reason": ["Erwartetes Zeitfenster noch nicht abgeschlossen"]}
        else:
            observed = compute_hydro_delta(event.get("station_id"), event_at + timedelta(minutes=lag[0]), lag[1] - lag[0])
            classified = classify_hydro_response(event, observed, pending_events)
        result = {
            "event_id": event.get("event_id"),
            "station_id": str(event.get("station_id")),
            "cell_id": event.get("cell_id"),
            "verified_at": current.isoformat().replace("+00:00", "Z"),
            "status": classified["status"],
            "lag_window_min": lag,
            "observed": {k: observed.get(k) for k in ("q_before_m3s", "q_after_max_m3s", "delta_q_m3s", "w_before_cm", "w_after_max_cm", "delta_w_cm")},
            "confidence": classified["confidence"],
            "interpretation": classified.get("interpretation", "plausibler Zusammenhang wird vorsichtig bewertet"),
            "reason": classified["reason"],
            "extra_windows_min": {str(w): compute_hydro_delta(event.get("station_id"), event_at, w) for w in HYDRO_EXTRA_WINDOWS_MIN} if event_at and classified["status"] != "pending" else {},
        }
        save_hydro_verification(result)
        if result["status"] != "pending":
            _update_event_status(result)
            done.add(str(result.get("event_id")))
        results.append(result)
    return results


def _read_verifications_since(days: int) -> list[dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = []
    if not HYDRO_VERIFICATION_PATH.exists():
        return rows
    with HYDRO_VERIFICATION_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = _parse_time(row.get("verified_at"))
            if t and t >= cutoff:
                rows.append(row)
    return rows


def get_hydro_verification_summary(days: int = 7) -> dict:
    rows = _read_verifications_since(days)
    summary: dict[str, Any] = {"days": days, "stations": {}}
    for station_id in sorted({str(r.get("station_id")) for r in rows}):
        station_rows = [r for r in rows if str(r.get("station_id")) == station_id]
        confirmed = [r for r in station_rows if r.get("status") == "confirmed"]
        lags = [
            r.get("lag_window_min", [None, None])[0]
            for r in confirmed
            if r.get("lag_window_min", [None])[0] is not None
        ]
        delta_q = [
            r.get("observed", {}).get("delta_q_m3s")
            for r in confirmed
            if r.get("observed", {}).get("delta_q_m3s") is not None
        ]
        delta_w = [
            r.get("observed", {}).get("delta_w_cm")
            for r in confirmed
            if r.get("observed", {}).get("delta_w_cm") is not None
        ]
        summary["stations"][station_id] = {
            "events_total": len(station_rows),
            "confirmed": sum(r.get("status") == "confirmed" for r in station_rows),
            "rejected": sum(r.get("status") == "rejected" for r in station_rows),
            "ambiguous": sum(r.get("status") == "ambiguous" for r in station_rows),
            "median_lag_min": median(lags) if lags else None,
            "typical_delta_q": median(delta_q) if delta_q else None,
            "typical_delta_w": median(delta_w) if delta_w else None,
        }
    HYDRO_VERIFICATION_SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with HYDRO_VERIFICATION_SUMMARY_PATH.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, sort_keys=True)
    return summary
