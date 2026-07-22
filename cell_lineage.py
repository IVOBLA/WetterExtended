"""Persistente Zell-Lineage-IDs für IR-Vorläuferzellen.

1L.1 vergibt stabile fachliche ``cell_id`` Werte für CB-IR-Tracks. Radar-
Übernahme und Score-Matching werden nur im State vorbereitet und noch nicht aktiv
umgesetzt.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import uuid

try:
    import fcntl  # POSIX (Raspian/Linux)
except Exception:
    fcntl = None
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import runtime_config
except Exception:  # pragma: no cover - Fallback für frühe Importphasen
    runtime_config = None

try:
    from config import (
        CELL_ID_PREFIX,
        CELL_LINEAGE_EVENTS_FILE,
        CELL_LINEAGE_STATE_DIR,
        CELL_LINEAGE_STATE_FILE,
        IR_RADAR_MATCH_SCORE_MIN,
        IR_RADAR_MATCH_SCORE_WEAK_MIN,
        IR_RADAR_MATCH_MAX_KM,
        IR_RADAR_MATCH_STRONG_KM,
        IR_RADAR_MATCH_LOOKBACK_MIN,
        IR_RADAR_MATCH_MAX_IR_AGE_MIN,
        IR_RADAR_MATCH_USE_PREDICTED_POSITION,
        IR_RADAR_MATCH_USE_GROWTH_SIGNALS,
        IR_RADAR_MATCH_USE_METPOT,
        IR_PRECURSOR_HIDE_WHEN_RADAR_MATCHED,
        IR_LEAD_TIME_LABELS_ENABLED,
        IR_LEAD_TIME_LABELS_FILE,
        CELL_LINEAGE_EVENT_SIGNATURE_MEMORY,
        IR_LEAD_TIME_LABELS_MAX_OPEN_MIN,
        IR_LEAD_TIME_LABELS_MIN_FINAL_AGE_MIN,
        IR_LEAD_TIME_LABELS_INCLUDE_NEGATIVES,
        IR_LEAD_TIME_LABELS_DEDUP_BY_CELL_ID,
        CELL_LINEAGE_SPLIT_MERGE_ENABLED,
        CELL_LINEAGE_PRIMARY_CHILD_POLICY,
        CELL_LINEAGE_PRIMARY_MERGE_POLICY,
        CELL_LINEAGE_KEEP_PARENT_CELL_ID_ON_SPLIT_PRIMARY,
        CELL_LINEAGE_CREATE_CHILD_CELL_IDS,
        CELL_LINEAGE_RECORD_ALIAS_IDS,
    )
except Exception:  # pragma: no cover
    CELL_ID_PREFIX = "WX"
    CELL_LINEAGE_STATE_DIR = "train_data/cell_lineage"
    CELL_LINEAGE_STATE_FILE = "cell_lineage_state.json"
    CELL_LINEAGE_EVENTS_FILE = "cell_lineage_events.jsonl"
    IR_RADAR_MATCH_SCORE_MIN = 0.70
    IR_RADAR_MATCH_SCORE_WEAK_MIN = 0.55
    IR_RADAR_MATCH_MAX_KM = 40.0
    IR_RADAR_MATCH_STRONG_KM = 15.0
    IR_RADAR_MATCH_LOOKBACK_MIN = 45.0
    IR_RADAR_MATCH_MAX_IR_AGE_MIN = 20.0
    IR_RADAR_MATCH_USE_PREDICTED_POSITION = True
    IR_RADAR_MATCH_USE_GROWTH_SIGNALS = True
    IR_RADAR_MATCH_USE_METPOT = True
    IR_PRECURSOR_HIDE_WHEN_RADAR_MATCHED = True
    IR_LEAD_TIME_LABELS_ENABLED = True
    IR_LEAD_TIME_LABELS_FILE = "ir_lead_time_labels.jsonl"
    CELL_LINEAGE_EVENT_SIGNATURE_MEMORY = 2000
    IR_LEAD_TIME_LABELS_MAX_OPEN_MIN = 90.0
    IR_LEAD_TIME_LABELS_MIN_FINAL_AGE_MIN = 20.0
    IR_LEAD_TIME_LABELS_INCLUDE_NEGATIVES = True
    IR_LEAD_TIME_LABELS_DEDUP_BY_CELL_ID = True
    CELL_LINEAGE_SPLIT_MERGE_ENABLED = True
    CELL_LINEAGE_PRIMARY_CHILD_POLICY = "strongest_core"
    CELL_LINEAGE_PRIMARY_MERGE_POLICY = "highest_core_ratio"
    CELL_LINEAGE_KEEP_PARENT_CELL_ID_ON_SPLIT_PRIMARY = True
    CELL_LINEAGE_CREATE_CHILD_CELL_IDS = True
    CELL_LINEAGE_RECORD_ALIAS_IDS = True


def _debug(msg: str) -> None:
    try:
        from debug_utils import debug_log
        debug_log(msg)
    except Exception:
        pass


def _cfg(name: str, default: Any) -> Any:
    if runtime_config is not None:
        try:
            return runtime_config.get(name, default)
        except Exception:
            pass
    return default


def _state_dir() -> Path:
    return Path(str(_cfg("CELL_LINEAGE_STATE_DIR", CELL_LINEAGE_STATE_DIR)))


def _state_path() -> Path:
    return _state_dir() / str(_cfg("CELL_LINEAGE_STATE_FILE", CELL_LINEAGE_STATE_FILE))


def _events_path() -> Path:
    return _state_dir() / str(_cfg("CELL_LINEAGE_EVENTS_FILE", CELL_LINEAGE_EVENTS_FILE))


_CELL_LINEAGE_DEFAULTS = {
    "parent_cell_id": None,
    "child_cell_ids": [],
    "merged_from_cell_ids": [],
    "merged_into_cell_id": None,
    "alias_cell_ids": [],
    "split_from_cell_id": None,
    "split_into_cell_ids": [],
    "lineage_events": [],
    "status": "active_tracked",
}


def _empty_state() -> dict:
    return {"version": 1, "date_counters": {}, "ir_to_cell": {}, "radar_to_cell": {}, "cells": {}}


def _ensure_cell_defaults(cell_id: str, cell: dict | None = None) -> dict:
    cell = cell if isinstance(cell, dict) else {}
    cell.setdefault("cell_id", str(cell_id))
    for key, val in _CELL_LINEAGE_DEFAULTS.items():
        if key not in cell:
            cell[key] = list(val) if isinstance(val, list) else val
        elif isinstance(val, list) and not isinstance(cell.get(key), list):
            cell[key] = []
    return cell


def _normalize_state(state: dict | None) -> dict:
    if not isinstance(state, dict):
        return _empty_state()
    out = _empty_state()
    out.update(state)
    for key in ("date_counters", "ir_to_cell", "radar_to_cell", "cells"):
        if not isinstance(out.get(key), dict):
            out[key] = {}
    out["version"] = 1

    # B280: Beim Lesen alter JSON-States Legacy-IR-IDs für Vergleiche/Matching
    # auf das kanonische Schema normalisieren. Schreibpfade für neue IDs bleiben
    # unverändert bei ir_<n>.
    normalized_ir_to_cell: dict[str, Any] = {}
    for raw_iid, mapped_cell_id in list(out.get("ir_to_cell", {}).items()):
        norm_iid = normalize_ir_id(raw_iid)
        if norm_iid:
            normalized_ir_to_cell[str(norm_iid)] = mapped_cell_id
    out["ir_to_cell"] = normalized_ir_to_cell

    for cid, cell in list(out.get("cells", {}).items()):
        cell = _ensure_cell_defaults(str(cid), cell)
        if cell.get("ir_track_id") is not None:
            cell["ir_track_id"] = normalize_ir_id(cell.get("ir_track_id"))
        # F4: ended ableiten — ended_at gesetzt impliziert ended=True
        if cell.get("ended_at") is not None or int(cell.get("ended_without_radar", 0) or 0) == 1:
            cell["ended"] = True
        # F2: radar_confirmed nur gültig wenn radar_track_id vorhanden
        if cell.get("radar_confirmed") is True and not cell.get("radar_track_id"):
            cell["radar_confirmed"] = False
            cell["status"] = "ir_precursor"
        # F1: last_seen darf nicht vor first_seen liegen
        _first = cell.get("first_seen_timestamp")
        _last = cell.get("last_seen_timestamp")
        if _first and _last:
            try:
                def _parse_ts_norm(s):
                    for fmt in ("%Y-%m-%d_%H-%M-%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
                        try:
                            return datetime.strptime(str(s).replace("+00:00", "Z"), fmt)
                        except ValueError:
                            pass
                    return None
                _dt_first = _parse_ts_norm(_first)
                _dt_last = _parse_ts_norm(_last)
                if _dt_first and _dt_last and _dt_last < _dt_first:
                    cell["last_seen_timestamp"] = _first
            except Exception:
                pass
        out["cells"][cid] = cell
    return out


def load_lineage_state() -> dict:
    path = _state_path()
    if not path.exists():
        return _empty_state()
    try:
        with path.open("r", encoding="utf-8") as f:
            return _normalize_state(json.load(f))
    except Exception as exc:
        _debug(f"[CELL-LINEAGE] State konnte nicht geladen werden ({path}): {exc}; nutze leeren State")
        # B453: Defekte Datei quarantaenieren statt sie liegen zu lassen.
        # B457 (Codex P1): Quarantaene NUR unter dem Save-Lock und NUR nach
        # ERNEUTER Pruefung. Ohne Lock konnte das os.replace hier einen soeben
        # von einem anderen Prozess atomar reparierten, VALIDEN State unter
        # demselben Pfadnamen wegquarantaenieren -- danach existierte gar
        # keine State-Datei mehr (date_counters-Reset, cell_id-Recycling).
        if isinstance(exc, (json.JSONDecodeError, ValueError)):
            lock_path = path.with_name(path.name + ".lock")
            try:
                with lock_path.open("a+", encoding="utf-8") as lock_fh:
                    if fcntl is not None:
                        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
                    try:
                        try:
                            with path.open("r", encoding="utf-8") as f2:
                                return _normalize_state(json.load(f2))
                        except FileNotFoundError:
                            # Ein anderer Prozess hat bereits quarantaeniert.
                            return _empty_state()
                        except (json.JSONDecodeError, ValueError):
                            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                            quarantine = path.with_name(f"{path.name}.corrupt.{ts}")
                            os.replace(path, quarantine)
                            _debug(f"[CELL-LINEAGE] Defekter State quarantaeniert: {quarantine}")
                    finally:
                        if fcntl is not None:
                            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
            except Exception as qexc:
                _debug(f"[CELL-LINEAGE] Quarantaene fehlgeschlagen ({path}): {qexc}")
        return _empty_state()


def save_lineage_state(state: dict) -> None:
    # B453: Zwei Dienste (wetterprojekt=main.py, wetterprojekt-admin=app.py)
    # schreiben denselben State. Der alte, prozessuebergreifend GETEILTE
    # Temp-Name (path + ".tmp") fuehrte bei ueberlappenden Schreibern zu
    # aneinandergehaengten JSON-Dokumenten ("Extra data"). Fix: eindeutiger
    # Temp-Name pro Aufruf (PID + uuid4) und Serialisierung via fcntl.flock
    # auf einer Lock-Datei -- Muster aus api_budget_guard.record_request.
    path = _state_path()
    lock_path = path.with_name(path.name + ".lock")
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as lock_fh:
            if fcntl is not None:
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
            try:
                with tmp.open("w", encoding="utf-8") as f:
                    json.dump(_normalize_state(state), f, indent=2, ensure_ascii=False)
                    f.write("\n")
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, path)
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
    except Exception as exc:
        _debug(f"[CELL-LINEAGE] State konnte nicht gespeichert werden ({path}): {exc}")
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass


def _write_status_path() -> Path:
    """B372/B378: Statusdatei ausserhalb des Eventledgers.

    Wenn ``train_data/cell_lineage`` selbst nicht angelegt oder beschrieben werden
    kann, darf der Fehlernachweis nicht im selben kaputten Verzeichnis landen.
    ``train_data/system`` wird als separater Admin-State-Pfad exportiert und ist
    damit ein unabhaengiger Ort fuer den letzten Lineage-Schreibstatus.
    """
    return Path("train_data/system/cell_lineage_write_status.json")


def _record_write_status(ok: bool, path: str, error: str | None = None) -> None:
    """B372: Persistenter, exportierter Nachweis ueber den letzten Schreibversuch.

    Vorher wurde jeder Schreibfehler ausschliesslich in eine debug_log-Zeile geschluckt.
    Da das systemd-Journal im Debug-Export zeitlich abgeschnitten wird, war ein
    Totalausfall der Event-Persistenz nicht nachweisbar: der Export vom 14.07.2026
    enthielt weder cell_lineage_events.jsonl noch cell_lineage_state.json, obwohl
    160 Objekte ein von record_cell_merge() gesetztes lineage_status trugen.
    """
    try:
        status_path = _write_status_path()
        status_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            prev = json.loads(status_path.read_text(encoding="utf-8"))
        except Exception:
            prev = {}
        status = {
            "last_attempt_utc": datetime.now(timezone.utc).isoformat(),
            "resolved_events_path": str(path),
            "cwd": os.getcwd(),
            "last_result": "ok" if ok else "error",
            "ok_count": int(prev.get("ok_count", 0)) + (1 if ok else 0),
            "error_count": int(prev.get("error_count", 0)) + (0 if ok else 1),
            "last_error": error if error else prev.get("last_error"),
            "last_error_utc": (
                datetime.now(timezone.utc).isoformat() if error else prev.get("last_error_utc")
            ),
        }
        status_path.write_text(
            json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )
    except Exception:
        pass  # Statusschreibung darf den Radarzyklus niemals stoppen


def append_lineage_event(event: dict) -> None:
    """B372: schreibt den Eventledger unter ABSOLUTEM Pfad und macht Fehler sichtbar.

    `_state_dir()` liefert einen RELATIVEN Pfad (Default "train_data/cell_lineage").
    Damit haengt das Ziel vom CWD des systemd-Dienstes ab. resolve() macht den Pfad
    eindeutig und protokolliert ihn in der Statusdatei, sodass ein abweichendes
    Arbeitsverzeichnis im Debug-Export sofort erkennbar ist.
    """
    path = None
    try:
        path = _events_path().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        _record_write_status(True, str(path))
    except Exception as exc:
        _debug(f"[CELL-LINEAGE] Event konnte nicht geschrieben werden: {exc}")
        _record_write_status(False, str(path) if path else "<unresolved>", f"{type(exc).__name__}: {exc}")


def _timestamp_str(timestamp: str | None = None) -> str:
    if timestamp:
        return str(timestamp)
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")


def _date_key(timestamp: str | None) -> str:
    raw = _timestamp_str(timestamp)
    for fmt in ("%Y-%m-%d_%H-%M-%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y%m%d_%H%M%S"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y%m%d")
        except ValueError:
            continue
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) >= 8:
        return digits[:8]
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def make_cell_id(timestamp: str, state: dict) -> str:
    state = _normalize_state(state)
    day = _date_key(timestamp)
    counters = state.setdefault("date_counters", {})
    counters[day] = int(counters.get(day, 0)) + 1
    prefix = str(_cfg("CELL_ID_PREFIX", CELL_ID_PREFIX) or "WX")
    return f"{prefix}-{day}-{counters[day]:04d}"


def _track_timestamp(track: dict, explicit: str | None) -> str:
    return _timestamp_str(explicit or track.get("source_timestamp") or track.get("first_seen_timestamp") or track.get("last_timestamp") or track.get("timestamp"))


def ensure_ir_track_cell_id(track: dict, *, timestamp: str | None = None, state: dict | None = None) -> tuple[dict, dict]:
    if not isinstance(track, dict):
        return track, _normalize_state(state) if state is not None else load_lineage_state()
    own_state = state is None
    state = load_lineage_state() if state is None else _normalize_state(state)
    ir_track_id = str(normalize_ir_id(track.get("ir_track_id") or track.get("ir_id") or track.get("id")) or "").strip()
    if ir_track_id:
        track["ir_track_id"] = ir_track_id
    ts = _track_timestamp(track, timestamp)

    existing_cell_id = track.get("cell_id") or (state.get("ir_to_cell", {}).get(ir_track_id) if ir_track_id else None)
    created = False
    if existing_cell_id:
        # F3: Abgelaufene ID nicht recyceln — neue ID vergeben wenn ended_at/label_written gesetzt
        _existing_cell = state.get("cells", {}).get(str(existing_cell_id), {})
        _is_ended = (
            _existing_cell.get("ended_at") is not None
            or int(_existing_cell.get("ended_without_radar", 0) or 0) == 1
            or _existing_cell.get("label_written") is True
        )
        if _is_ended:
            # Veraltetes Mapping entfernen, frische ID vergeben
            if ir_track_id:
                state.setdefault("ir_to_cell", {}).pop(str(ir_track_id), None)
            cell_id = make_cell_id(ts, state)
            track["cell_id"] = cell_id
            created = True
        else:
            cell_id = str(existing_cell_id)
            track["cell_id"] = cell_id
    else:
        cell_id = make_cell_id(ts, state)
        track["cell_id"] = cell_id
        created = True

    if ir_track_id:
        state.setdefault("ir_to_cell", {})[ir_track_id] = cell_id
    cell = state.setdefault("cells", {}).setdefault(cell_id, {
        "cell_id": cell_id,
        "status": "ir_precursor",
        "first_seen_source": track.get("first_seen_source") or "ir108",
        "first_seen_timestamp": track.get("first_seen_timestamp") or ts,
        "last_seen_timestamp": ts,
        "ir_track_id": ir_track_id or None,
        "radar_track_id": track.get("radar_track_id"),
        "radar_confirmed": False,
        "ended": False,
        "aliases": [],
    })
    cell["last_seen_timestamp"] = ts
    cell["ir_track_id"] = cell.get("ir_track_id") or ir_track_id or None
    cell["radar_track_id"] = cell.get("radar_track_id") or track.get("radar_track_id")
    if track.get("radar_confirmed") is True:
        cell["radar_confirmed"] = True
        cell["status"] = "radar_confirmed"
    track.setdefault("first_seen_source", cell.get("first_seen_source") or "ir108")
    track.setdefault("first_seen_timestamp", cell.get("first_seen_timestamp") or ts)

    if created:
        append_lineage_event({
            "event_type": "ir_cell_id_created",
            "cell_id": cell_id,
            "ir_track_id": ir_track_id,
            "timestamp": ts,
            "source": track.get("first_seen_source") or track.get("source_type") or "ir108",
        })
    if own_state:
        save_lineage_state(state)
    return track, state


def ensure_ir_tracks_cell_ids(tracks: list[dict], *, timestamp: str | None = None) -> list[dict]:
    state = load_lineage_state()
    changed = False
    out = []
    for track in tracks or []:
        before = track.get("cell_id") if isinstance(track, dict) else None
        new_track, state = ensure_ir_track_cell_id(track, timestamp=timestamp, state=state)
        changed = changed or (isinstance(track, dict) and track.get("cell_id") != before)
        out.append(new_track)
    if changed:
        save_lineage_state(state)
    return out


def get_cell_id_for_ir_track(ir_track_id: str) -> str | None:
    state = load_lineage_state()
    return state.get("ir_to_cell", {}).get(str(normalize_ir_id(ir_track_id)))



# ─────────────────────────────────────────────────────────────────────────────
# 1L.4: ML-Lead-Time-Labels IR-Vorläufer → Radarbestätigung
# ─────────────────────────────────────────────────────────────────────────────

_LABEL_TYPE = "ir_to_radar_lead_time"
_IR_FEATURE_KEYS = (
    "bt_min_k", "bt_mean_k", "bt_trend_k_per_min", "cloud_height_m",
    "cloud_height_trend_m_per_min", "area_px", "area_growth_km2_per_min",
    "overshooting_top", "cloud_age_min", "anvil_extension_km", "cape", "li",
    "arome_li", "cin", "lapse_700_500", "lightning_count_10km",
    "lightning_count", "nowcast_rr_mm15", "core_ratio",
)
_RADAR_FEATURE_KEYS = ("radar_area_px", "radar_intensity_label", "core_ratio")


def labels_path() -> Path:
    return _state_dir() / str(_cfg("IR_LEAD_TIME_LABELS_FILE", IR_LEAD_TIME_LABELS_FILE))


def _label_key(label: dict) -> str:
    if bool(_cfg("IR_LEAD_TIME_LABELS_DEDUP_BY_CELL_ID", IR_LEAD_TIME_LABELS_DEDUP_BY_CELL_ID)):
        outcome = "pos" if int(label.get("became_radar_cell") or 0) == 1 else "neg"
        return f"{label.get('cell_id')}|{label.get('label_type') or _LABEL_TYPE}|{outcome}"
    return f"{label.get('cell_id')}|{label.get('label_type') or _LABEL_TYPE}|{label.get('created_at_utc','')}"


def append_ir_lead_time_label(label: dict) -> None:
    if not bool(_cfg("IR_LEAD_TIME_LABELS_ENABLED", IR_LEAD_TIME_LABELS_ENABLED)) or not isinstance(label, dict):
        return
    try:
        path = labels_path(); path.parent.mkdir(parents=True, exist_ok=True)
        if _label_key(label) in load_existing_lead_time_label_keys():
            return
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(label, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception as exc:
        _debug(f"[CELL-LINEAGE] Lead-Time-Label konnte nicht geschrieben werden: {exc}")


def load_existing_lead_time_label_keys() -> set[str]:
    keys: set[str] = set()
    path = labels_path()
    if not path.exists():
        return keys
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict) and obj.get("cell_id"):
                        if obj.get("ir_track_id") is not None:
                            obj["ir_track_id"] = normalize_ir_id(obj.get("ir_track_id"))
                        keys.add(_label_key(obj))
                except Exception:
                    continue
    except Exception:
        return keys
    return keys


def _cell_first_seen(cell: dict, ir_track: dict | None = None) -> str | None:
    for src in (ir_track or {}, cell or {}):
        for key in ("first_seen_timestamp", "first_seen", "created_at", "timestamp"):
            if src.get(key):
                return str(src.get(key))
    return None


def _cell_radar_confirmed_at(cell: dict, event: dict | None = None) -> str | None:
    for src in (event or {}, cell or {}):
        for key in ("radar_first_confirmed", "radar_confirmed_at", "timestamp", "last_seen_timestamp"):
            if src.get(key):
                return str(src.get(key))
    return None


def normalize_ir_id(raw_id) -> str | None:
    """B280: Legacy-Schema IR-NNN (falls in Altdaten vorhanden) auf kanonisches
    ir_<number> mappen. Neue IDs werden NIE im Legacy-Schema geschrieben."""
    if raw_id is None:
        return None
    s = str(raw_id)
    if s.startswith("ir_"):
        return s
    if s.startswith("IR-"):
        num_part = s[3:].lstrip("0") or "0"
        if num_part.isdigit():
            return f"ir_{int(num_part)}"
    return s


def compute_lead_time_min(ir_first_seen: str | None, radar_first_confirmed: str | None) -> float | None:
    a, b = _parse_dt(ir_first_seen), _parse_dt(radar_first_confirmed)
    if not a or not b:
        return None
    return round((b - a).total_seconds() / 60.0, 3)


def _copy_label_features(label: dict, cell: dict, ir_track: dict | None, radar_obj: dict | None = None) -> dict:
    for src in (cell or {}, ir_track or {}):
        for key in _IR_FEATURE_KEYS:
            if key in src and src.get(key) is not None and key not in label:
                label[key] = src.get(key)
    if "lightning_count" in label and "lightning_count_10km" not in label:
        label["lightning_count_10km"] = label.pop("lightning_count")
    for src in (radar_obj or {}, cell or {}):
        if not isinstance(src, dict):
            continue
        if src.get("area_px") is not None:
            label.setdefault("radar_area_px", src.get("area_px"))
        if src.get("area") is not None:
            label.setdefault("radar_area_px", src.get("area"))
        if src.get("intensity_label") is not None:
            label.setdefault("radar_intensity_label", src.get("intensity_label"))
        if src.get("radar_intensity_label") is not None:
            label.setdefault("radar_intensity_label", src.get("radar_intensity_label"))
        if src.get("core_ratio") is not None:
            label.setdefault("core_ratio", src.get("core_ratio"))
    return label


def build_positive_ir_lead_time_label(cell: dict, ir_track: dict | None, radar_obj: dict | None, event: dict | None = None) -> dict:
    ir_first = _cell_first_seen(cell, ir_track)
    radar_at = _cell_radar_confirmed_at(cell, event)
    label = {
        "label_type": _LABEL_TYPE, "cell_id": (cell or {}).get("cell_id") or (ir_track or {}).get("cell_id") or (radar_obj or {}).get("cell_id"),
        "ir_track_id": normalize_ir_id((ir_track or {}).get("ir_track_id") or (cell or {}).get("ir_track_id")),
        "radar_track_id": (radar_obj or {}).get("id") or (radar_obj or {}).get("track_id") or (cell or {}).get("radar_track_id"),
        "became_radar_cell": 1, "ended_without_radar": 0,
        "ir_first_seen": ir_first, "radar_first_confirmed": radar_at,
        "lead_time_min": compute_lead_time_min(ir_first, radar_at),
        "source": (ir_track or {}).get("first_seen_source") or (cell or {}).get("first_seen_source") or "ir108",
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "match_score": (event or {}).get("score") or (radar_obj or {}).get("lineage_match_score"),
        "match_decision": (event or {}).get("decision") or (radar_obj or {}).get("lineage_match_decision"),
        "match_reason": (event or {}).get("reason") or (radar_obj or {}).get("lineage_match_reason"),
    }
    return _copy_label_features(label, cell or {}, ir_track, radar_obj)


def build_negative_ir_lead_time_label(cell: dict, ir_track: dict | None, *, ended_at: str | None = None, reason: str = "expired_without_radar") -> dict:
    ended_at = ended_at or _timestamp_str(None)
    label = {
        "label_type": _LABEL_TYPE, "cell_id": (cell or {}).get("cell_id") or (ir_track or {}).get("cell_id"),
        "ir_track_id": normalize_ir_id((ir_track or {}).get("ir_track_id") or (cell or {}).get("ir_track_id")),
        "radar_track_id": None, "became_radar_cell": 0, "ended_without_radar": 1,
        "ir_first_seen": _cell_first_seen(cell, ir_track), "radar_first_confirmed": None,
        "lead_time_min": None, "ended_at": ended_at, "negative_reason": reason,
        "source": (ir_track or {}).get("first_seen_source") or (cell or {}).get("first_seen_source") or "ir108",
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return _copy_label_features(label, cell or {}, ir_track, None)


def maybe_write_positive_ir_lead_time_label(cell_id: str, *, ir_track: dict | None = None, radar_obj: dict | None = None, event: dict | None = None, state: dict | None = None) -> dict | None:
    if not bool(_cfg("IR_LEAD_TIME_LABELS_ENABLED", IR_LEAD_TIME_LABELS_ENABLED)) or not cell_id:
        return None
    state = load_lineage_state() if state is None else _normalize_state(state)
    cell = state.setdefault("cells", {}).setdefault(str(cell_id), {"cell_id": str(cell_id)})
    label = build_positive_ir_lead_time_label(cell, ir_track, radar_obj, event)
    existing = load_existing_lead_time_label_keys()
    if _label_key(label) in existing:
        return None
    neg_probe = dict(label); neg_probe["became_radar_cell"] = 0
    if _label_key(neg_probe) in existing:
        label["supersedes_negative"] = True
    append_ir_lead_time_label(label)
    cell.update({"became_radar_cell": 1, "ended_without_radar": 0, "radar_first_confirmed": label.get("radar_first_confirmed"), "lead_time_min": label.get("lead_time_min"), "label_written": True, "ended": True})
    return label


def finalize_expired_ir_precursors(*, timestamp: str | None = None, active_ir_tracks: list[dict] | None = None, state: dict | None = None) -> list[dict]:
    if not bool(_cfg("IR_LEAD_TIME_LABELS_ENABLED", IR_LEAD_TIME_LABELS_ENABLED)) or not bool(_cfg("IR_LEAD_TIME_LABELS_INCLUDE_NEGATIVES", IR_LEAD_TIME_LABELS_INCLUDE_NEGATIVES)):
        return []
    # Bewahre explizite Radarbestätigungen des übergebenen In-Memory-States,
    # bevor _normalize_state() Legacy-Zellen ohne radar_track_id bereinigt. So
    # erzeugt die Finalisierung keine negativen Labels für bereits bestätigte
    # Zellen, selbst wenn der aufrufende Test/Code nur radar_confirmed setzt.
    raw_radar_confirmed_cell_ids = {
        str(cell_id)
        for cell_id, cell in ((state or {}).get("cells", {}) if isinstance(state, dict) else {}).items()
        if isinstance(cell, dict) and (cell.get("radar_confirmed") is True or cell.get("status") == "radar_confirmed")
    }
    state = load_lineage_state() if state is None else _normalize_state(state)
    now_s = _timestamp_str(timestamp); now = _parse_dt(now_s)
    active_by_cell = {str(t.get("cell_id")): t for t in (active_ir_tracks or []) if isinstance(t, dict) and t.get("cell_id")}
    keys = load_existing_lead_time_label_keys(); written = []
    max_open = float(_cfg("IR_LEAD_TIME_LABELS_MAX_OPEN_MIN", IR_LEAD_TIME_LABELS_MAX_OPEN_MIN))
    min_final = float(_cfg("IR_LEAD_TIME_LABELS_MIN_FINAL_AGE_MIN", IR_LEAD_TIME_LABELS_MIN_FINAL_AGE_MIN))
    for cell_id, cell in list(state.get("cells", {}).items()):
        if str(cell_id) in raw_radar_confirmed_cell_ids:
            continue
        if not isinstance(cell, dict) or cell.get("radar_confirmed") is True or cell.get("status") == "radar_confirmed" or int(cell.get("became_radar_cell") or 0) == 1:
            continue
        probe_pos = {"cell_id": cell_id, "label_type": _LABEL_TYPE, "became_radar_cell": 1}
        probe_neg = {"cell_id": cell_id, "label_type": _LABEL_TYPE, "became_radar_cell": 0}
        if _label_key(probe_pos) in keys or _label_key(probe_neg) in keys:
            continue
        first = _parse_dt(_cell_first_seen(cell, active_by_cell.get(cell_id)))
        last = _parse_dt((active_by_cell.get(cell_id) or {}).get("last_seen_timestamp") or cell.get("last_seen_timestamp") or _cell_first_seen(cell))
        if not now or not first or not last:
            continue
        if (now - first).total_seconds() / 60.0 < max_open or (now - last).total_seconds() / 60.0 < min_final:
            continue
        if cell_id in active_by_cell and (now - last).total_seconds() / 60.0 < max_open:
            continue
        label = build_negative_ir_lead_time_label(cell, active_by_cell.get(cell_id), ended_at=now_s)
        append_ir_lead_time_label(label)
        cell.update({"became_radar_cell": 0, "ended_without_radar": 1, "ended_at": now_s, "negative_reason": label.get("negative_reason"), "label_written": True, "ended": True})
        written.append(label); keys.add(_label_key(label))
    return written


def update_ir_lead_time_labels(radar_objects: list[dict] | None = None, ir_tracks: list[dict] | None = None, lineage_events: list[dict] | None = None, *, timestamp: str | None = None) -> list[dict]:
    state = load_lineage_state(); out = []
    for ev in lineage_events or []:
        if isinstance(ev, dict) and ev.get("event_type") == "ir_to_radar_confirmation":
            cid = ev.get("cell_id")
            ir = next((t for t in (ir_tracks or []) if isinstance(t, dict) and t.get("cell_id") == cid), None)
            ro = next((r for r in (radar_objects or []) if isinstance(r, dict) and r.get("cell_id") == cid), None)
            label = maybe_write_positive_ir_lead_time_label(str(cid), ir_track=ir, radar_obj=ro, event=ev, state=state)
            if label:
                out.append({"event_type": "ir_lead_time_label_written", "cell_id": cid, "timestamp": _timestamp_str(timestamp), "became_radar_cell": 1})
    for label in finalize_expired_ir_precursors(timestamp=timestamp, active_ir_tracks=ir_tracks, state=state):
        out.append({"event_type": "ir_precursor_ended_without_radar", "cell_id": label.get("cell_id"), "timestamp": _timestamp_str(timestamp), "became_radar_cell": 0})
        out.append({"event_type": "ir_lead_time_label_written", "cell_id": label.get("cell_id"), "timestamp": _timestamp_str(timestamp), "became_radar_cell": 0})
    save_lineage_state(state)
    return out


def ir_precursor_diagnosis_summary(labels: list[dict]) -> dict:
    """B280: Aggregierte Diagnose für Admin-Panel/Export."""
    total = len(labels)
    matched = [l for l in labels if int(l.get("became_radar_cell") or 0) == 1]
    lead_times = [l.get("lead_time_min") for l in matched if l.get("lead_time_min") is not None]
    reject_reasons: dict[str, int] = {}
    for l in labels:
        if int(l.get("became_radar_cell") or 0) == 0:
            r = l.get("negative_reason") or "unknown"
            reject_reasons[r] = reject_reasons.get(r, 0) + 1
    return {
        "ir_precursors_total": total,
        "matched_count": len(matched),
        "positive_label_count": len(matched),
        "median_lead_time_min": statistics.median(lead_times) if lead_times else None,
        "top_reject_reasons": sorted(reject_reasons.items(), key=lambda kv: -kv[1])[:5],
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1L.2: deterministisches Score-Matching IR↔Radar
# ─────────────────────────────────────────────────────────────────────────────

def _float_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        val = float(value)
        return val if math.isfinite(val) else None
    except Exception:
        return None


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    if raw.endswith("Z"):
        raw2 = raw[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(raw2).astimezone(timezone.utc).replace(tzinfo=None)
        except Exception:
            pass
    for fmt in ("%Y-%m-%d_%H-%M-%S", "%Y-%m-%dT%H:%M:%S", "%Y%m%d_%H%M%S"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw).replace(tzinfo=None)
    except Exception:
        return None


def _track_time(track: dict) -> str | None:
    return track.get("last_seen_timestamp") or track.get("last_timestamp") or track.get("timestamp") or track.get("source_timestamp") or track.get("first_seen_timestamp")


def _age_min(track: dict, timestamp: str | None) -> float:
    explicit = _float_or_none(track.get("cloud_age_min") if track.get("cloud_age_min") is not None else track.get("age_min"))
    target = _parse_dt(timestamp)
    src = _parse_dt(_track_time(track))
    if target and src:
        return max(0.0, (target - src).total_seconds() / 60.0)
    return max(0.0, explicit or 0.0)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dp = math.radians(float(lat2) - float(lat1))
    dl = math.radians(float(lon2) - float(lon1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1 - a)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dl = math.radians(float(lon2) - float(lon1))
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def angle_diff_deg(a: float, b: float) -> float:
    return abs((float(a) - float(b) + 180.0) % 360.0 - 180.0)


def predict_ir_position(ir_track: dict, target_timestamp: str | None = None, dt_min: float | None = None) -> tuple[float, float]:
    lat = _float_or_none(ir_track.get("lat"))
    lon = _float_or_none(ir_track.get("lon"))
    if lat is None or lon is None:
        raise ValueError("missing IR coordinates")
    vx = _float_or_none(ir_track.get("vx_deg_min"))
    vy = _float_or_none(ir_track.get("vy_deg_min"))
    if vx is None or vy is None:
        return lat, lon
    if dt_min is None:
        target = _parse_dt(target_timestamp)
        src = _parse_dt(_track_time(ir_track))
        dt_min = (target - src).total_seconds() / 60.0 if target and src else 0.0
    return lat + vy * float(dt_min), lon + vx * float(dt_min)


def _proximity_points(distance: float | None, max_points: float) -> float:
    if distance is None:
        return 0.0
    max_km = float(_cfg("IR_RADAR_MATCH_MAX_KM", IR_RADAR_MATCH_MAX_KM))
    strong = float(_cfg("IR_RADAR_MATCH_STRONG_KM", IR_RADAR_MATCH_STRONG_KM))
    if distance <= strong:
        return max_points
    if distance >= max_km:
        return 0.0
    return max_points * (max_km - distance) / max(0.001, max_km - strong)


def _vector_bearing(obj: dict) -> float | None:
    vx = _float_or_none(obj.get("vx_deg_min") or obj.get("vx"))
    vy = _float_or_none(obj.get("vy_deg_min") or obj.get("vy"))
    if vx is None or vy is None or (abs(vx) + abs(vy) == 0):
        return None
    return (math.degrees(math.atan2(vx, vy)) + 360.0) % 360.0


def _growth_score(ir_track: dict) -> float:
    signals = 0
    total = 4
    if (_float_or_none(ir_track.get("bt_trend_k_per_min")) or 0.0) < 0: signals += 1
    if (_float_or_none(ir_track.get("cloud_height_trend_m_per_min")) or 0.0) > 0: signals += 1
    if (_float_or_none(ir_track.get("area_growth_km2_per_min")) or 0.0) > 0: signals += 1
    if bool(ir_track.get("overshooting_top")): signals += 1
    return signals / total


def _metpot_score(radar_obj: dict, ir_track: dict, weather_context: dict | None) -> float:
    vals = {}
    for src in (weather_context or {}, ir_track or {}, radar_obj or {}):
        if isinstance(src, dict):
            vals.update({k: src.get(k) for k in ("cape", "li", "arome_li", "cin", "lapse_700_500", "ship_index", "lightning_count") if src.get(k) is not None})
    score = 0.0; n = 0
    for key, val in vals.items():
        v = _float_or_none(val)
        if v is None: continue
        n += 1
        if key == "cape": score += min(1.0, max(0.0, v / 2000.0))
        elif key in ("li", "arome_li"): score += min(1.0, max(0.0, (-v + 2.0) / 8.0))
        elif key == "cin": score += min(1.0, max(0.0, 1.0 - abs(v) / 200.0))
        elif key == "lapse_700_500": score += min(1.0, max(0.0, (v - 5.0) / 3.0))
        elif key == "ship_index": score += min(1.0, max(0.0, v / 2.0))
        elif key == "lightning_count": score += min(1.0, max(0.0, v / 10.0))
    return min(1.0, score / n) if n else 0.0


def _debug_ir_match_candidate(ir_id: str | None, radar_id: str | None, age_min: float | None, dist_km: float | None, reject_reason: str | None) -> None:
    age = float(age_min) if age_min is not None else -1.0
    dist = float(dist_km) if dist_km is not None else -1.0
    _debug(
        f"[IR-MATCH][B280] ir_id={ir_id or ''} radar_id={radar_id or ''} age_min={age:.1f} "
        f"dist_km={dist:.3f} max_age={_cfg('IR_RADAR_MATCH_MAX_IR_AGE_MIN', IR_RADAR_MATCH_MAX_IR_AGE_MIN)} "
        f"lookback={_cfg('IR_RADAR_MATCH_LOOKBACK_MIN', IR_RADAR_MATCH_LOOKBACK_MIN)} reject_reason={reject_reason or 'accepted'}"
    )


def compute_ir_radar_match_score(radar_obj: dict, ir_track: dict, *, timestamp: str | None = None, weather_context: dict | None = None) -> dict:
    rid = str(radar_obj.get("id") or radar_obj.get("track_id") or "")
    iid = str(normalize_ir_id(ir_track.get("ir_track_id") or ir_track.get("ir_id") or ir_track.get("id")) or "")
    base = {"matched": False, "score": 0.0, "decision": "rejected", "reason": "rejected", "ir_id": normalize_ir_id(ir_track.get("ir_id")), "ir_track_id": iid, "radar_track_id": rid, "cell_id": ir_track.get("cell_id"), "centroid_distance_km": None, "predicted_centroid_distance_km": None, "ir_age_min": None, "direction_error_deg": None, "growth_score": 0.0, "metpot_score": 0.0, "score_components": {"distance": 0.0, "predicted_position": 0.0, "time": 0.0, "direction": 0.0, "growth": 0.0, "metpot": 0.0}}
    rlat, rlon = _float_or_none(radar_obj.get("lat")), _float_or_none(radar_obj.get("lon"))
    ilat, ilon = _float_or_none(ir_track.get("lat")), _float_or_none(ir_track.get("lon"))
    if None in (rlat, rlon, ilat, ilon):
        base["reason"] = "missing_coords"; _debug_ir_match_candidate(iid, rid, base.get("ir_age_min"), base.get("centroid_distance_km"), base["reason"]); return base
    if ir_track.get("radar_confirmed") is True and str(ir_track.get("radar_track_id") or rid) != rid:
        base["reason"] = "already_radar_confirmed"; _debug_ir_match_candidate(iid, rid, base.get("ir_age_min"), base.get("centroid_distance_km"), base["reason"]); return base
    max_km = float(_cfg("IR_RADAR_MATCH_MAX_KM", IR_RADAR_MATCH_MAX_KM))
    dist = haversine_km(rlat, rlon, ilat, ilon); base["centroid_distance_km"] = round(dist, 3)
    if dist > max_km:
        base["reason"] = "distance_too_far"; _debug_ir_match_candidate(iid, rid, age_min=None, dist_km=dist, reject_reason=base["reason"]); return base
    age = _age_min(ir_track, timestamp); base["ir_age_min"] = round(age, 3)
    if age > float(_cfg("IR_RADAR_MATCH_LOOKBACK_MIN", IR_RADAR_MATCH_LOOKBACK_MIN)):
        base["reason"] = "ir_too_old"; _debug_ir_match_candidate(iid, rid, age, dist, base["reason"]); return base
    comps = base["score_components"]
    comps["distance"] = _proximity_points(dist, 0.30)
    if bool(_cfg("IR_RADAR_MATCH_USE_PREDICTED_POSITION", IR_RADAR_MATCH_USE_PREDICTED_POSITION)):
        plat, plon = predict_ir_position(ir_track, target_timestamp=timestamp)
        pdist = haversine_km(rlat, rlon, plat, plon); base["predicted_centroid_distance_km"] = round(pdist, 3)
        if any(_float_or_none(ir_track.get(k)) is not None for k in ("vx_deg_min", "vy_deg_min")):
            comps["predicted_position"] = _proximity_points(pdist, 0.25)
    full_age = float(_cfg("IR_RADAR_MATCH_MAX_IR_AGE_MIN", IR_RADAR_MATCH_MAX_IR_AGE_MIN))
    lookback = float(_cfg("IR_RADAR_MATCH_LOOKBACK_MIN", IR_RADAR_MATCH_LOOKBACK_MIN))
    comps["time"] = 0.15 if age <= full_age else 0.15 * max(0.0, (lookback - age) / max(0.001, lookback - full_age))
    ib, rb = _vector_bearing(ir_track), _vector_bearing(radar_obj)
    if ib is not None and rb is not None:
        err = angle_diff_deg(ib, rb); base["direction_error_deg"] = round(err, 3); comps["direction"] = 0.10 * max(0.0, 1.0 - err / 180.0)
    if bool(_cfg("IR_RADAR_MATCH_USE_GROWTH_SIGNALS", IR_RADAR_MATCH_USE_GROWTH_SIGNALS)):
        gs = _growth_score(ir_track); base["growth_score"] = round(gs, 3); comps["growth"] = 0.10 * gs
    if bool(_cfg("IR_RADAR_MATCH_USE_METPOT", IR_RADAR_MATCH_USE_METPOT)):
        ms = _metpot_score(radar_obj, ir_track, weather_context); base["metpot_score"] = round(ms, 3); comps["metpot"] = 0.10 * ms
    score = sum(comps.values()); base["score"] = round(score, 4)
    strong_min = float(_cfg("IR_RADAR_MATCH_SCORE_MIN", IR_RADAR_MATCH_SCORE_MIN))
    weak_min = float(_cfg("IR_RADAR_MATCH_SCORE_WEAK_MIN", IR_RADAR_MATCH_SCORE_WEAK_MIN))
    if score >= strong_min:
        base.update({"matched": True, "decision": "strong", "reason": "score_ge_min"})
    elif score >= weak_min:
        base.update({"matched": True, "decision": "weak", "reason": "score_ge_weak_unique"})
    else:
        base["reason"] = "score_below_min"
    _debug_ir_match_candidate(iid, rid, age, dist, None if base.get("matched") else base.get("reason"))
    for k, v in list(comps.items()): comps[k] = round(v, 4)
    return base


def _real_cell_id(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(str(_cfg("CELL_ID_PREFIX", CELL_ID_PREFIX) or "WX") + "-")


_IR_MATCH_DIAG_FILE = "ir_radar_match_diagnostics.jsonl"


def _match_diagnostics_path() -> Path:
    return _state_dir() / str(_cfg("IR_RADAR_MATCH_DIAGNOSTICS_FILE", _IR_MATCH_DIAG_FILE))


def _record_match_diagnostics(candidates: list[dict], radar_objects: list[dict], ir_tracks: list[dict], selected: list[dict], timestamp: str | None) -> None:
    """B310: Aggregierte Diagnose warum IR->Radar-Matches (nicht) zustande kommen.
    Schreibt NUR aggregierte Zaehler (keine Einzel-Kandidaten-Details) — geringe
    Schreiblast, um die 0-Match-Rate offline analysierbar zu machen (siehe B310-Prompt)."""
    if not bool(_cfg("IR_RADAR_MATCH_DIAGNOSTICS_ENABLED", True)):
        return
    try:
        eligible_radar = sum(1 for r in (radar_objects or []) if not _real_cell_id((r or {}).get("cell_id")))
        reason_counts: dict[str, int] = {}
        decision_counts: dict[str, int] = {}
        for m in candidates:
            _reason = m.get("reason") or "unknown"
            _decision = m.get("decision") or "unknown"
            reason_counts[_reason] = reason_counts.get(_reason, 0) + 1
            decision_counts[_decision] = decision_counts.get(_decision, 0) + 1
        rec = {
            "ts_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "timestamp": _timestamp_str(timestamp),
            "radar_object_count": len(radar_objects or []),
            "radar_eligible_count": eligible_radar,
            "ir_track_count": len(ir_tracks or []),
            "candidate_pair_count": len(candidates),
            "selected_count": len(selected),
            "decision_counts": decision_counts,
            "reason_counts": reason_counts,
        }
        path = _match_diagnostics_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as exc:
        _debug(f"[CELL-LINEAGE] Match-Diagnostics konnte nicht geschrieben werden: {exc}")


_IR_LINEAGE_FALLBACK_FILE = "ir_radar_lineage_fallback_events.jsonl"


def _lineage_fallback_path() -> Path:
    return _state_dir() / str(_cfg("IR_RADAR_LINEAGE_FALLBACK_FILE", _IR_LINEAGE_FALLBACK_FILE))


def record_lineage_fallback_error(exc: Exception, *, timestamp: str | None = None) -> None:
    """B342: Wird von main.py aufgerufen, wenn _score_match_ir_radar_lineage()
    eine Exception wirft und main.py silent auf
    _legacy_ir_radar_distance_match() zurueckfaellt (die KEIN
    ir_to_radar_confirmation-Event/Positiv-Label schreibt). Vorher nur per
    debug_log() protokolliert und dadurch im Debug-Export nicht
    nachvollziehbar."""
    try:
        import traceback as _tb
        rec = {
            "ts_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "timestamp": _timestamp_str(timestamp),
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "traceback": "".join(_tb.format_exception(type(exc), exc, exc.__traceback__))[-4000:],
        }
        path = _lineage_fallback_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as _log_exc:
        _debug(f"[CELL-LINEAGE] Fallback-Error-Logging fehlgeschlagen: {_log_exc}")


def select_ir_radar_matches(radar_objects: list[dict], ir_tracks: list[dict], *, timestamp: str | None = None, weather_context: dict | None = None) -> tuple[list[dict], dict]:
    candidates = []
    for ri, robj in enumerate(radar_objects or []):
        # B263: Nur bereits in diesem Zyklus lineage-bestätigte Objekte überspringen.
        # Früher wurde auf _real_cell_id(cell_id) geprüft — das schließt ALLE Radar-
        # Objekte aus, weil object_tracking.py jeder Zelle eine WX-ID vergibt.
        if robj.get("lineage_status") == "radar_confirmed":
            continue
        for ii, itrack in enumerate(ir_tracks or []):
            m = compute_ir_radar_match_score(robj, itrack, timestamp=timestamp, weather_context=weather_context)
            if m.get("centroid_distance_km") is not None:
                m["radar_index"] = ri; m["ir_index"] = ii; candidates.append(m)
    candidates.sort(key=lambda m: (bool(m.get("matched")), float(m.get("score") or 0), -float(m.get("ir_age_min") or 9999), -float((ir_tracks[m["ir_index"]] or {}).get("bt_min_k") or 9999), float((ir_tracks[m["ir_index"]] or {}).get("cloud_height_m") or 0)), reverse=True)
    by_ir: dict[int, list[dict]] = {}
    for m in candidates:
        if m.get("matched"):
            by_ir.setdefault(m["ir_index"], []).append(m)
    allowed_ir_radar = set()
    for ii, ms in by_ir.items():
        ms.sort(key=lambda m: (float((radar_objects[m["radar_index"]] or {}).get("core_ratio") or 0), float((radar_objects[m["radar_index"]] or {}).get("area") or (radar_objects[m["radar_index"]] or {}).get("area_km2") or 0), float(m.get("score") or 0)), reverse=True)
        allowed_ir_radar.add((ii, ms[0]["radar_index"]))
    used_radar, used_ir, selected = set(), set(), []
    for m in candidates:
        ri, ii = m["radar_index"], m["ir_index"]
        if not m.get("matched") or ri in used_radar or ii in used_ir or (ii, ri) not in allowed_ir_radar:
            continue
        selected.append(m); used_radar.add(ri); used_ir.add(ii)
    _record_match_diagnostics(candidates, radar_objects, ir_tracks, selected, timestamp)
    return selected, {"candidates": candidates, "selected_count": len(selected)}


# B392: Eine IR-Bestaetigung ist eine Sensorbestaetigung und darf ein bereits
# bestaetigtes strukturelles Radarereignis nicht ueberschreiben.
_STRUCTURAL_RADAR_LINEAGE_STATUSES = frozenset({
    "merged",
    "split",
    "split_primary",
    "split_child",
})


def has_structural_radar_lineage(radar_obj: dict | None) -> bool:
    obj = radar_obj or {}
    if str(obj.get("transition_event") or "") in {"merge", "split"}:
        return True
    if str(obj.get("lineage") or "") in {"merged", "split"}:
        return True
    return str(obj.get("lineage_status") or "") in _STRUCTURAL_RADAR_LINEAGE_STATUSES


def resolve_ir_radar_cell_id(radar_obj: dict | None, ir_track: dict | None) -> str:
    """B392: kanonische cell_id fuer einen IR↔Radar-Match.

    Bei einem bereits bestaetigten Radar-Merge/Split bleibt die strukturelle
    Radar-cell_id erhalten. Im Normalfall gilt weiterhin die etablierte
    1L.2-Regel: Radar uebernimmt die IR-Vorlaeufer-ID.
    """
    radar_cid = str((radar_obj or {}).get("cell_id") or "").strip()
    ir_cid = str((ir_track or {}).get("cell_id") or "").strip()

    if has_structural_radar_lineage(radar_obj) and radar_cid:
        return radar_cid
    return ir_cid or radar_cid


def _reconcile_ir_alias_state(
    state: dict,
    *,
    source_ir_cell_id: str | None,
    canonical_cell_id: str,
    radar_track_id: str,
    ir_track_id: str,
    timestamp: str | None,
) -> None:
    """B392: alte IR-Zellidentitaet als bestaetigten Alias markieren.

    Der Alias bleibt fuer Debugging/Lead-Time nachvollziehbar, darf aber weder
    als zweite physikalische Zelle weiterlaufen noch spaeter ein negatives
    `ended_without_radar`-Label erhalten.
    """
    source_id = str(source_ir_cell_id or "").strip()
    canonical_id = str(canonical_cell_id or "").strip()
    if not source_id or not canonical_id or source_id == canonical_id:
        return

    cells = state.setdefault("cells", {})
    source = cells.setdefault(source_id, {"cell_id": source_id})
    canonical = cells.setdefault(canonical_id, {"cell_id": canonical_id})
    _ensure_cell_defaults(source_id, source)
    _ensure_cell_defaults(canonical_id, canonical)

    # Bereits gesammelte IR-Metadaten in die kanonische Zelle uebernehmen, aber
    # vorhandene kanonische Werte nicht ueberschreiben.
    for key in (
        "first_seen_timestamp",
        "first_seen_source",
        "created_at",
        "cloud_age_min",
        *_IR_FEATURE_KEYS,
    ):
        if canonical.get(key) is None and source.get(key) is not None:
            canonical[key] = source.get(key)

    _append_unique(canonical.setdefault("alias_cell_ids", []), source_id)

    source.update({
        "canonical_cell_id": canonical_id,
        "is_alias": True,
        "status": "radar_confirmed",
        "radar_confirmed": True,
        "radar_track_id": radar_track_id or source.get("radar_track_id"),
        "ir_track_id": ir_track_id or source.get("ir_track_id"),
        "became_radar_cell": 1,
        "ended_without_radar": 0,
        "ended": True,
        "last_seen_timestamp": _timestamp_str(timestamp),
    })


def apply_ir_radar_lineage_match(
    radar_obj: dict,
    ir_track: dict,
    match: dict,
    state: dict | None = None,
    *,
    timestamp: str | None = None,
) -> tuple[dict, dict, dict]:
    """Verknuepft IR-Vorlaeufer und Radarobjekt ohne Radar-Lineage zu zerstoeren."""
    state = load_lineage_state() if state is None else _normalize_state(state)

    if not ir_track.get("cell_id"):
        ir_track, state = ensure_ir_track_cell_id(
            ir_track,
            timestamp=timestamp,
            state=state,
        )

    source_ir_cell_id = str(ir_track.get("cell_id") or "").strip()
    preserve_structural = has_structural_radar_lineage(radar_obj)
    cell_id = resolve_ir_radar_cell_id(radar_obj, ir_track)

    if not cell_id:
        # Defensiver Fallback; regulaer hat ensure_ir_track_cell_id() bereits
        # eine fachliche ID erzeugt.
        ir_track, state = ensure_ir_track_cell_id(
            ir_track,
            timestamp=timestamp,
            state=state,
        )
        source_ir_cell_id = str(ir_track.get("cell_id") or "").strip()
        cell_id = resolve_ir_radar_cell_id(radar_obj, ir_track)

    ir_track_id = str(
        normalize_ir_id(
            ir_track.get("ir_track_id")
            or ir_track.get("ir_id")
            or ir_track.get("id")
        )
        or ""
    )
    radar_track_id = str(
        radar_obj.get("id")
        or radar_obj.get("track_id")
        or ""
    )

    preserved_lineage_status = radar_obj.get("lineage_status")
    preserved_lineage_event = radar_obj.get("lineage_event")

    # Nur IR-Metadaten setzen. Strukturelle Radar-Felder bleiben unangetastet.
    radar_obj.update({
        "cell_id": cell_id,
        "ir_match_id": ir_track.get("ir_id"),
        "ir_track_id": ir_track_id or ir_track.get("ir_id"),
        "ir_status": "radar_confirmed",
        "ir_radar_confirmed": True,
        "ir_is_potential_new_cell": False,
        "ir_display_as_precursor": False,
        "ir_only_precursor": 0.0,
        "ir_lineage_event": "ir_to_radar_confirmation",
        "lineage_match_score": match.get("score"),
        "lineage_match_decision": match.get("decision"),
        "lineage_match_reason": match.get("reason"),
        "lineage_match_distance_km": match.get("centroid_distance_km"),
        "lineage_match_predicted_distance_km": match.get(
            "predicted_centroid_distance_km"
        ),
    })

    if preserve_structural:
        # Merge-/Split-Status und strukturelles lineage_event erhalten.
        radar_obj["lineage_status"] = preserved_lineage_status
        if preserved_lineage_event is not None:
            radar_obj["lineage_event"] = preserved_lineage_event
        else:
            radar_obj.pop("lineage_event", None)
        if source_ir_cell_id and source_ir_cell_id != cell_id:
            _append_unique(radar_obj.setdefault("alias_cell_ids", []), source_ir_cell_id)
    else:
        # Unveraendertes 1L.2-Normalverhalten.
        radar_obj["lineage_status"] = "radar_confirmed"
        radar_obj["lineage_event"] = "ir_to_radar_confirmation"

    for key in (
        "area_growth_km2_per_min",
        "cloud_height_trend_m_per_min",
        "bt_min_k",
        "bt_mean_k",
        "bt_trend_k_per_min",
        "cloud_age_min",
        "anvil_extension_km",
        "overshooting_top",
    ):
        if key in ir_track:
            radar_obj.setdefault(
                "ir_" + key if key.startswith(("area", "cloud_height")) else key,
                ir_track.get(key),
            )

    # Beide In-Memory-Objekte verwenden nach dem Match dieselbe kanonische ID.
    ir_track.update({
        "cell_id": cell_id,
        "radar_track_id": radar_obj.get("id"),
        "status": "radar_confirmed",
        "radar_confirmed": True,
        "is_potential_new_cell": False,
        "display_as_precursor": False,
        "ir_only_precursor": 0.0,
    })

    if radar_track_id:
        state.setdefault("radar_to_cell", {})[radar_track_id] = cell_id
    if ir_track_id:
        state.setdefault("ir_to_cell", {})[ir_track_id] = cell_id

    _reconcile_ir_alias_state(
        state,
        source_ir_cell_id=source_ir_cell_id,
        canonical_cell_id=cell_id,
        radar_track_id=radar_track_id,
        ir_track_id=ir_track_id,
        timestamp=timestamp,
    )

    cell = state.setdefault("cells", {}).setdefault(
        cell_id,
        {"cell_id": cell_id},
    )
    _ensure_cell_defaults(cell_id, cell)

    cell.update({
        "radar_confirmed": True,
        "radar_track_id": radar_track_id or cell.get("radar_track_id"),
        "ir_track_id": ir_track_id or cell.get("ir_track_id"),
        "last_seen_timestamp": _timestamp_str(timestamp),
        "radar_confirmed_at": _timestamp_str(timestamp),
    })

    # record_cell_merge()/record_cell_split() haben den fachlichen Status bereits
    # festgelegt. Nur der Normalfall darf ihn zu radar_confirmed aendern.
    if not preserve_structural:
        cell["status"] = "radar_confirmed"

    for key in _IR_FEATURE_KEYS:
        if key in ir_track and ir_track.get(key) is not None:
            cell[key] = ir_track.get(key)

    event = {
        "event_type": "ir_to_radar_confirmation",
        "cell_id": cell_id,
        "ir_track_id": ir_track_id,
        "radar_track_id": radar_track_id,
        "timestamp": _timestamp_str(timestamp),
        "score": match.get("score"),
        "decision": match.get("decision"),
        "reason": match.get("reason"),
        "centroid_distance_km": match.get("centroid_distance_km"),
        "predicted_centroid_distance_km": match.get(
            "predicted_centroid_distance_km"
        ),
        "preserved_structural_lineage": bool(preserve_structural),
    }
    if source_ir_cell_id and source_ir_cell_id != cell_id:
        event["source_ir_cell_id"] = source_ir_cell_id

    append_lineage_event(event)
    match["cell_id"] = cell_id
    match["event"] = event
    return radar_obj, ir_track, state

def update_cell_lineage(radar_objects: list[dict], ir_tracks: list[dict], *, timestamp: str | None = None, weather_context: dict | None = None) -> tuple[list[dict], list[dict], list[dict]]:
    state = load_lineage_state()
    for t in ir_tracks or []:
        ensure_ir_track_cell_id(t, timestamp=timestamp, state=state)
    matches, _info = select_ir_radar_matches(radar_objects or [], ir_tracks or [], timestamp=timestamp, weather_context=weather_context)
    events = []
    for m in matches:
        r, ir = radar_objects[m["radar_index"]], ir_tracks[m["ir_index"]]
        apply_ir_radar_lineage_match(r, ir, m, state=state, timestamp=timestamp)
        events.append(m.get("event"))
        label = maybe_write_positive_ir_lead_time_label(str(ir.get("cell_id") or r.get("cell_id")), ir_track=ir, radar_obj=r, event=m.get("event"), state=state)
        if label:
            label_event = {"event_type": "ir_lead_time_label_written", "cell_id": label.get("cell_id"), "timestamp": _timestamp_str(timestamp), "became_radar_cell": 1}
            append_lineage_event(label_event)
            events.append(label_event)
    for ir in ir_tracks or []:
        if ir.get("radar_confirmed") is not True and int(ir.get("became_radar_cell") or 0) != 1:
            ir.setdefault("status", "ir_precursor")
            ir.setdefault("radar_confirmed", False)
            ir.setdefault("is_potential_new_cell", True)
            ir.setdefault("display_as_precursor", True)
            ir.setdefault("ir_only_precursor", 1.0)
            cell = state.setdefault("cells", {}).setdefault(ir.get("cell_id"), {"cell_id": ir.get("cell_id")}) if ir.get("cell_id") else None
            if isinstance(cell, dict):
                for key in _IR_FEATURE_KEYS:
                    if key in ir and ir.get(key) is not None:
                        cell[key] = ir.get(key)
    for label in finalize_expired_ir_precursors(timestamp=timestamp, active_ir_tracks=ir_tracks, state=state):
        for label_event in (
            {"event_type": "ir_precursor_ended_without_radar", "cell_id": label.get("cell_id"), "timestamp": _timestamp_str(timestamp), "became_radar_cell": 0},
            {"event_type": "ir_lead_time_label_written", "cell_id": label.get("cell_id"), "timestamp": _timestamp_str(timestamp), "became_radar_cell": 0},
        ):
            append_lineage_event(label_event)
            events.append(label_event)
    save_lineage_state(state)
    return radar_objects or [], ir_tracks or [], [e for e in events if e]

# ─────────────────────────────────────────────────────────────────────────────
# B213: Split-/Merge-Lineage über fachliche cell_id
# ─────────────────────────────────────────────────────────────────────────────

def _obj_track_id(obj: dict | None) -> str:
    return str((obj or {}).get("id") or (obj or {}).get("track_id") or "").strip()


def _num(obj: dict | None, *keys: str, default: float = 0.0) -> float:
    for key in keys:
        val = _float_or_none((obj or {}).get(key))
        if val is not None:
            return val
    return default


def _append_unique(seq: list, values) -> list:
    for val in values if isinstance(values, (list, tuple, set)) else [values]:
        if val is not None and val not in seq:
            seq.append(val)
    return seq


def _prev_map(previous_objects: dict | list | None) -> dict[str, dict]:
    if isinstance(previous_objects, dict):
        vals = previous_objects.values() if all(isinstance(v, dict) for v in previous_objects.values()) else previous_objects.items()
        out = {}
        for k, v in (previous_objects.items()):
            if isinstance(v, dict):
                out[str(k)] = v
                oid = _obj_track_id(v)
                if oid:
                    out[oid] = v
        return out
    out = {}
    for obj in previous_objects or []:
        if isinstance(obj, dict):
            oid = _obj_track_id(obj)
            if oid:
                out[oid] = obj
    return out


def get_cell_id_for_radar_track(radar_track_id: str | int, state: dict | None = None) -> str | None:
    if radar_track_id is None:
        return None
    state = load_lineage_state() if state is None else _normalize_state(state)
    return state.get("radar_to_cell", {}).get(str(radar_track_id))


def ensure_radar_track_cell_id(radar_obj: dict, *, timestamp: str | None = None, state: dict | None = None) -> tuple[dict, dict]:
    if not isinstance(radar_obj, dict):
        return radar_obj, _normalize_state(state) if state is not None else load_lineage_state()
    own_state = state is None
    state = load_lineage_state() if state is None else _normalize_state(state)
    rid = _obj_track_id(radar_obj)
    ts = _track_timestamp(radar_obj, timestamp)
    cell_id = radar_obj.get("cell_id") or (state.get("radar_to_cell", {}).get(rid) if rid else None)
    if not cell_id:
        cell_id = make_cell_id(ts, state)
    cell_id = str(cell_id)
    radar_obj["cell_id"] = cell_id
    if rid:
        state.setdefault("radar_to_cell", {})[rid] = cell_id
    cell = state.setdefault("cells", {}).setdefault(cell_id, {"cell_id": cell_id})
    _ensure_cell_defaults(cell_id, cell)
    cell.update({"radar_track_id": rid or cell.get("radar_track_id"), "last_seen_timestamp": ts})
    if cell.get("status") in (None, "active_tracked", "ir_precursor"):
        cell["status"] = "radar_confirmed"
    if own_state:
        save_lineage_state(state)
    return radar_obj, state


def select_primary_child(children: list[dict], *, policy: str | None = None) -> dict | None:
    valid = [c for c in (children or []) if isinstance(c, dict)]
    if not valid:
        return None
    policy = policy or str(_cfg("CELL_LINEAGE_PRIMARY_CHILD_POLICY", CELL_LINEAGE_PRIMARY_CHILD_POLICY))
    if policy == "strongest_core":
        return max(enumerate(valid), key=lambda it: (_num(it[1], "core_ratio"), _num(it[1], "area", "area_px", "area_km2"), -_num(it[1], "parent_distance_km", "distance_to_parent_km", default=0.0), -it[0]))[1]
    return valid[0]


def select_primary_merge_parent(parent_objects: list[dict], *, policy: str | None = None, survivor_cell_id: str | None = None) -> dict | None:
    """B377: delegiert an die gemeinsame Policy (tracking/primary_policy.py).

    Vorher entschied hier `highest_core_ratio`, waehrend object_tracking.py die
    Radar-ID nach groesster alter Polygonflaeche vergab -- zwei widersprechende
    Regeln. Jetzt ist tracking/primary_policy.py die einzige Quelle der Wahrheit
    fuer beide Ebenen.
    """
    valid = [p for p in (parent_objects or []) if isinstance(p, dict)]
    if not valid:
        return None
    policy = policy or str(_cfg("CELL_LINEAGE_PRIMARY_MERGE_POLICY", CELL_LINEAGE_PRIMARY_MERGE_POLICY))
    try:
        from tracking.primary_policy import select_primary_parent
        return select_primary_parent(valid, policy=policy, survivor_id=survivor_cell_id, id_key="cell_id")
    except Exception as exc:
        _debug(f"[B377] Primary-Policy nicht verfügbar, Legacy-Auswahl: {exc}")
        if policy == "highest_core_ratio":
            return max(enumerate(valid), key=lambda it: (_num(it[1], "core_ratio"), _num(it[1], "area", "area_px", "area_km2"), -it[0]))[1]
        return valid[0]


def _event_signature(event_type: str, parent_ids: list[str], child_ids: list[str]) -> str:
    """B371: Stabile, ZEITSTEMPELFREIE Identitaet eines Lineage-Ereignisses.

    Ein Merge/Split ist ein Uebergangsereignis, kein Dauerzustand. Solange dieselbe
    Parent-/Child-Konstellation besteht, ist es DASSELBE Ereignis -- auch wenn
    object_tracking.py in jedem Folgeframe erneut lineage="merged" meldet.

    Der Timestamp darf NICHT in die Signatur einfliessen, sonst waere jedes Frame
    ein neues Ereignis (genau der Defekt, den B371 behebt).
    """
    payload = "|".join([
        str(event_type),
        ",".join(sorted(str(p) for p in (parent_ids or []) if p)),
        ",".join(sorted(str(c) for c in (child_ids or []) if c)),
    ])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _event_already_emitted(state: dict, signature: str) -> bool:
    """True, wenn zu dieser Signatur bereits ein Ereignis geschrieben wurde."""
    return signature in set(state.get("emitted_event_signatures") or [])


def _mark_event_emitted(state: dict, signature: str, timestamp: str) -> None:
    """Merkt die Signatur im State und begrenzt das Gedaechtnis (Pi: RAM/Disk).

    Begrenzung auf die letzten CELL_LINEAGE_EVENT_SIGNATURE_MEMORY Eintraege. Der Wert
    ist grosszuegig gegenueber der beobachteten Last (24 h Konvektion: 160 Merge-Frames,
    23 Serien) und verhindert unbegrenztes Wachstum der State-Datei.
    """
    sigs = state.setdefault("emitted_event_signatures", [])
    if signature in sigs:
        return
    sigs.append(signature)
    limit = int(_cfg("CELL_LINEAGE_EVENT_SIGNATURE_MEMORY", CELL_LINEAGE_EVENT_SIGNATURE_MEMORY))
    if len(sigs) > limit:
        del sigs[: len(sigs) - limit]
    state.setdefault("emitted_event_last_seen", {})[signature] = str(timestamp)


def record_cell_merge(parent_cell_ids: list[str], merged_obj: dict, *, timestamp: str | None = None, state: dict | None = None) -> dict | None:
    if not bool(_cfg("CELL_LINEAGE_SPLIT_MERGE_ENABLED", CELL_LINEAGE_SPLIT_MERGE_ENABLED)) or not isinstance(merged_obj, dict):
        return None
    own_state = state is None
    if state is None:
        state = load_lineage_state()
    else:
        state.update(_normalize_state(state))
    ts = _timestamp_str(timestamp)
    parent_cell_ids = list(dict.fromkeys(str(cid) for cid in (parent_cell_ids or []) if cid))
    if not parent_cell_ids:
        return None
    primary = str(merged_obj.get("cell_id") or parent_cell_ids[0])
    merged_obj.update({"cell_id": primary, "lineage_status": "merged", "merged_from_cell_ids": parent_cell_ids})
    aliases = [cid for cid in parent_cell_ids if cid != primary]
    if bool(_cfg("CELL_LINEAGE_RECORD_ALIAS_IDS", CELL_LINEAGE_RECORD_ALIAS_IDS)):
        merged_obj["alias_cell_ids"] = aliases
    rid = _obj_track_id(merged_obj)
    if rid:
        state.setdefault("radar_to_cell", {})[rid] = primary
    pcell = state.setdefault("cells", {}).setdefault(primary, {"cell_id": primary})
    _ensure_cell_defaults(primary, pcell)
    _append_unique(pcell.setdefault("merged_from_cell_ids", []), parent_cell_ids)
    _append_unique(pcell.setdefault("alias_cell_ids", []), aliases)
    pcell["status"] = "radar_confirmed"
    pcell["last_seen_timestamp"] = ts
    for cid in parent_cell_ids:
        cell = state.setdefault("cells", {}).setdefault(cid, {"cell_id": cid})
        _ensure_cell_defaults(cid, cell)
        if cid != primary:
            cell["merged_into_cell_id"] = primary
            cell["status"] = "merged"
    # B371: Ereignis-Identitaet ueber zeitstempelfreie Signatur. Solange dieselbe
    # Parent-Konstellation auf dieselbe primary cell_id mergt, ist es DASSELBE
    # Ereignis. Der State (last_seen, Aliase, radar_to_cell) wurde oben bereits
    # aktualisiert und bleibt in jedem Frame aktuell -- nur das EVENT ist einmalig.
    signature = _event_signature("cell_merge", parent_cell_ids, [primary])
    if _event_already_emitted(state, signature):
        state.setdefault("emitted_event_last_seen", {})[signature] = ts
        if own_state:
            save_lineage_state(state)
        return None

    event = {"event_type": "cell_merge", "timestamp": ts, "cell_id": primary, "merged_from_cell_ids": parent_cell_ids, "primary_cell_id": primary, "radar_track_id": rid, "parent_radar_track_ids": list(merged_obj.get("parents") or []), "event_signature": signature}
    if merged_obj.get("unresolved_parent_ids"):
        event["unresolved_parent_ids"] = list(merged_obj.get("unresolved_parent_ids") or [])
    _append_unique(pcell.setdefault("lineage_events", []), event)
    append_lineage_event(event)
    _mark_event_emitted(state, signature, ts)
    if own_state:
        save_lineage_state(state)
    return event


def record_cell_split(parent_cell_id: str, child_objects: list[dict], *, timestamp: str | None = None, state: dict | None = None) -> list[dict]:
    if not bool(_cfg("CELL_LINEAGE_SPLIT_MERGE_ENABLED", CELL_LINEAGE_SPLIT_MERGE_ENABLED)) or not parent_cell_id:
        return []
    own_state = state is None
    if state is None:
        state = load_lineage_state()
    else:
        state.update(_normalize_state(state))
    ts = _timestamp_str(timestamp)
    children = [c for c in (child_objects or []) if isinstance(c, dict)]
    if len(children) < 2:
        return []
    primary_child = select_primary_child(children)
    child_cell_ids = []
    for child in children:
        is_primary = child is primary_child
        if is_primary and bool(_cfg("CELL_LINEAGE_KEEP_PARENT_CELL_ID_ON_SPLIT_PRIMARY", CELL_LINEAGE_KEEP_PARENT_CELL_ID_ON_SPLIT_PRIMARY)):
            cid = str(parent_cell_id)
            child["lineage_status"] = "split_primary"
        else:
            cid = str(child.get("cell_id") or "")
            if (not cid or cid == str(parent_cell_id)) and bool(_cfg("CELL_LINEAGE_CREATE_CHILD_CELL_IDS", CELL_LINEAGE_CREATE_CHILD_CELL_IDS)):
                cid = make_cell_id(ts, state)
            child["split_from_cell_id"] = str(parent_cell_id)
            child["lineage_status"] = "split_child"
        child["cell_id"] = cid
        child["parent_cell_id"] = str(parent_cell_id)
        child_cell_ids.append(cid)
        rid = _obj_track_id(child)
        if rid:
            state.setdefault("radar_to_cell", {})[rid] = cid
        cstate = state.setdefault("cells", {}).setdefault(cid, {"cell_id": cid})
        _ensure_cell_defaults(cid, cstate)
        cstate["parent_cell_id"] = str(parent_cell_id)
        if cid != str(parent_cell_id):
            cstate["split_from_cell_id"] = str(parent_cell_id)
        cstate["status"] = "split" if cid != str(parent_cell_id) else "radar_confirmed"
    parent = state.setdefault("cells", {}).setdefault(str(parent_cell_id), {"cell_id": str(parent_cell_id)})
    _ensure_cell_defaults(str(parent_cell_id), parent)
    _append_unique(parent.setdefault("split_into_cell_ids", []), child_cell_ids)
    _append_unique(parent.setdefault("child_cell_ids", []), child_cell_ids)
    parent["status"] = "split"
    # B371: identische Ereignis-Semantik wie beim Merge -- ein Split ist ein
    # Uebergang, kein Dauerzustand.
    signature = _event_signature("cell_split", [str(parent_cell_id)], child_cell_ids)
    if _event_already_emitted(state, signature):
        state.setdefault("emitted_event_last_seen", {})[signature] = ts
        if own_state:
            save_lineage_state(state)
        return []

    event = {"event_type": "cell_split", "timestamp": ts, "parent_cell_id": str(parent_cell_id), "child_cell_ids": child_cell_ids, "primary_child_cell_id": primary_child.get("cell_id") if primary_child else None, "parent_radar_track_id": (children[0].get("parents") or [None])[0], "child_radar_track_ids": [_obj_track_id(c) for c in children], "event_signature": signature}
    _append_unique(parent.setdefault("lineage_events", []), event)
    append_lineage_event(event)
    _mark_event_emitted(state, signature, ts)
    if own_state:
        save_lineage_state(state)
    return [event]


def _dedupe_frame_cell_ids(radar_objects: list[dict], state: dict, *, timestamp: str | None = None) -> list[dict]:
    """B454: Erzwingt cell_id-Eindeutigkeit pro Frame (Radar-vs-Radar).

    Tragen zwei lebende Radar-Objekte dieselbe cell_id (z. B. weil ein
    Merge-Survivor die Identitaet eines WEITERLEBENDEN Parents geerbt hat;
    beobachtet 2026-07-21: WX-20260721-0007 doppelt ueber ~12 Frames), behaelt
    das Objekt mit der aelteren Identitaet die cell_id (lineage != "merged"
    bevorzugt, dann fruehestes first_seen, dann Track-ID als deterministischer
    Tiebreak). Jedes weitere Objekt erhaelt eine frische make_cell_id() und
    ein Lineage-Event "cell_id_collision_resolved".
    """
    events: list[dict] = []
    ts = _timestamp_str(timestamp)
    groups: dict[str, list[dict]] = {}
    for obj in radar_objects:
        if not isinstance(obj, dict):
            continue
        cid = obj.get("cell_id")
        rid = _obj_track_id(obj)
        if cid and rid:
            groups.setdefault(str(cid), []).append(obj)
    for cid, objs in groups.items():
        if len(objs) < 2:
            continue

        def _keep_rank(o: dict):
            return (
                1 if str(o.get("lineage") or "") == "merged" else 0,
                str(o.get("first_seen") or "9999"),
                str(_obj_track_id(o)),
            )

        objs_sorted = sorted(objs, key=_keep_rank)
        keeper = objs_sorted[0]
        for obj in objs_sorted[1:]:
            rid = str(_obj_track_id(obj))
            new_cid = make_cell_id(ts, state)
            occupied_cell_ids = {
                str(mapped_cid)
                for mapping_name in ("radar_to_cell", "ir_to_cell")
                for mapped_cid in state.get(mapping_name, {}).values()
                if mapped_cid
            } | {str(existing_cid) for existing_cid in state.get("cells", {})}
            while new_cid in occupied_cell_ids:
                new_cid = make_cell_id(ts, state)
            obj["cell_id"] = new_cid
            state.setdefault("radar_to_cell", {})[rid] = new_cid
            cell = state.setdefault("cells", {}).setdefault(new_cid, {"cell_id": new_cid})
            _ensure_cell_defaults(new_cid, cell)
            cell["status"] = "radar_confirmed"
            cell["last_seen_timestamp"] = ts
            cell["radar_track_id"] = rid
            # B454: Die Eltern-Verknuepfung darf bei der Umschluesselung NICHT
            # verloren gehen. Der neue Zellen-Datensatz uebernimmt die
            # Merge-Lineage vom Objekt (record_cell_merge hat sie an die alte,
            # geteilte cell_id geschrieben), und merged_into_cell_id
            # konsumierter Parents wird auf die neue cell_id umgehaengt. Der
            # lebende Keeper-Parent traegt kein merged_into_cell_id (er war
            # primary) und bleibt unangetastet.
            merged_from = [str(c) for c in (obj.get("merged_from_cell_ids") or []) if c]
            if merged_from:
                _append_unique(cell.setdefault("merged_from_cell_ids", []), merged_from)
                _append_unique(
                    cell.setdefault("alias_cell_ids", []),
                    [str(c) for c in (obj.get("alias_cell_ids") or []) if c],
                )
                for pcid in merged_from:
                    parent_cell = state.get("cells", {}).get(pcid)
                    if isinstance(parent_cell, dict) and parent_cell.get("merged_into_cell_id") == str(cid):
                        parent_cell["merged_into_cell_id"] = new_cid
                # B458 (Codex P2): record_cell_merge hat merged_from/aliases und
                # das cell_merge-Event auf den KEEPER (alte, geteilte cell_id)
                # geschrieben. Nach der Umschluesselung gehoert diese Merge-
                # Metadatenlage zum Survivor (new_cid); auf dem weiterhin
                # eigenstaendigen Keeper waere sie eine falsche Historie
                # ("Parent mergte aus sich selbst + konsumiertem Parent").
                # Exakt die Eintraege DIESES Merges entfernen -- identifiziert
                # ueber die Parent-Konstellation bzw. die zeitstempelfreie
                # event_signature (B371). Aeltere, echte Merge-Historie des
                # Keepers mit anderen Parents bleibt erhalten.
                keeper_cell = state.get("cells", {}).get(str(cid))
                if isinstance(keeper_cell, dict):
                    _sig = _event_signature("cell_merge", merged_from, [str(cid)])
                    keeper_cell["lineage_events"] = [
                        e for e in keeper_cell.get("lineage_events") or []
                        if not (isinstance(e, dict) and e.get("event_signature") == _sig)
                    ]
                    _mf_this = {str(c) for c in merged_from}
                    keeper_cell["merged_from_cell_ids"] = [
                        c for c in keeper_cell.get("merged_from_cell_ids") or []
                        if str(c) not in _mf_this
                    ]
                    _alias_this = {str(c) for c in (obj.get("alias_cell_ids") or [])}
                    keeper_cell["alias_cell_ids"] = [
                        c for c in keeper_cell.get("alias_cell_ids") or []
                        if str(c) not in _alias_this
                    ]
            event = {
                "event_type": "cell_id_collision_resolved",
                "timestamp": ts,
                "cell_id": new_cid,
                "previous_cell_id": str(cid),
                "radar_track_id": rid,
                "kept_by_radar_track_id": _obj_track_id(keeper),
            }
            if merged_from:
                event["merged_from_cell_ids"] = merged_from
            _append_unique(cell.setdefault("lineage_events", []), [event])
            append_lineage_event(event)
            events.append(event)
    return events


def update_split_merge_lineage(radar_objects: list[dict], previous_objects: dict | list | None = None, *, timestamp: str | None = None) -> list[dict]:
    if not bool(_cfg("CELL_LINEAGE_SPLIT_MERGE_ENABLED", CELL_LINEAGE_SPLIT_MERGE_ENABLED)):
        return []
    state = load_lineage_state(); events = []; prev = _prev_map(previous_objects); by_id = {_obj_track_id(o): o for o in (radar_objects or []) if isinstance(o, dict) and _obj_track_id(o)}
    for obj in radar_objects or []:
        if isinstance(obj, dict) and not (obj.get("lineage") == "merged" and len(obj.get("parents") or []) >= 2):
            ensure_radar_track_cell_id(obj, timestamp=timestamp, state=state)
    for obj in radar_objects or []:
        if not isinstance(obj, dict):
            continue
        if obj.get("lineage") == "merged" and len(obj.get("parents") or []) >= 2:
            parent_cids=[]; unresolved=[]; parent_objs=[]
            for pid in obj.get("parents") or []:
                po = prev.get(str(pid), {})
                cid = state.get("radar_to_cell", {}).get(str(pid)) or po.get("cell_id")
                if cid:
                    parent_cids.append(str(cid)); parent_objs.append(dict(po, cell_id=str(cid)))
                else:
                    unresolved.append(str(pid))
            parent_cids = list(dict.fromkeys(parent_cids))
            if not obj.get("cell_id") and parent_cids:
                # B268: Falls der ueberlebende Tracking-Survivor (obj["id"]) bereits
                # VOR diesem Merge eine eigene etablierte cell_id hatte (er IST einer
                # der Parents, B117-Kontinuitaet ueber groesste alte Konturflaeche),
                # hat diese Identitaetskontinuitaet Vorrang vor der core_ratio-Policy.
                # Sonst "stiehlt" eine frisch entstandene, momentan kompaktere Zelle
                # die Identitaet einer etablierten, laenger getrackten Zelle.
                _own_rid = _obj_track_id(obj)
                _own_cid = state.get("radar_to_cell", {}).get(str(_own_rid)) if _own_rid else None
                # B377: Der B268-Survivor-Vorrang ist jetzt eine POLICY-OPTION
                # ("survivor_first"), nicht mehr die unausweichliche Regel. Vorher
                # ueberstimmte er die konfigurierte Policy im Normalfall komplett --
                # das Admin-Panel suggerierte Einfluss, den die Einstellung nicht hatte.
                primary_parent = select_primary_merge_parent(
                    parent_objs, survivor_cell_id=(_own_cid if _own_cid in parent_cids else None)
                )
                obj["cell_id"] = (primary_parent or {}).get("cell_id") or parent_cids[0]
            if unresolved:
                obj["unresolved_parent_ids"] = unresolved
            ev = record_cell_merge(parent_cids, obj, timestamp=timestamp, state=state) if parent_cids else None
            # B454: radar_to_cell-Eintraege KONSUMIERTER Merge-Parents entfernen.
            # Konsumiert = der Parent-Track existiert in diesem Frame nicht mehr
            # als eigenes Objekt und ist nicht der Survivor. Lebt ein Parent
            # weiter, behaelt er seine eigene Zuordnung -- eine etwaige Kollision
            # mit dem Survivor loest der Frame-Dedup am Funktionsende auf.
            _survivor_rid = str(_obj_track_id(obj))
            for _pid in obj.get("parents") or []:
                _pid_s = str(_pid)
                if _pid_s != _survivor_rid and _pid_s not in by_id:
                    state.get("radar_to_cell", {}).pop(_pid_s, None)
            if ev:
                events.append(ev)
            elif unresolved:
                ev = {"event_type": "cell_merge", "timestamp": _timestamp_str(timestamp), "cell_id": obj.get("cell_id"), "radar_track_id": _obj_track_id(obj), "parent_radar_track_ids": list(obj.get("parents") or []), "unresolved_parent_ids": unresolved}
                append_lineage_event(ev); events.append(ev)
        if obj.get("lineage") == "split" and obj.get("parents"):
            pid = str((obj.get("parents") or [None])[0]); parent_cid = state.get("radar_to_cell", {}).get(pid) or (prev.get(pid) or {}).get("cell_id")
            siblings = [o for o in (radar_objects or []) if isinstance(o, dict) and pid in [str(x) for x in (o.get("parents") or [])]]
            if parent_cid and len(siblings) > 1:
                for ev in record_cell_split(str(parent_cid), siblings, timestamp=timestamp, state=state):
                    if ev not in events: events.append(ev)
            elif not parent_cid:
                ev = {"event_type": "cell_split", "timestamp": _timestamp_str(timestamp), "parent_radar_track_id": pid, "child_radar_track_ids": [_obj_track_id(c) for c in siblings or [obj]], "unresolved_parent_id": pid}
                append_lineage_event(ev); events.append(ev)
    for pobj in prev.values():
        if isinstance(pobj, dict) and len(pobj.get("children") or []) > 1:
            parent_cid = state.get("radar_to_cell", {}).get(_obj_track_id(pobj)) or pobj.get("cell_id")
            children = [by_id.get(str(cid)) for cid in (pobj.get("children") or [])]
            children = [c for c in children if isinstance(c, dict)]
            if parent_cid and len(children) > 1:
                for ev in record_cell_split(str(parent_cid), children, timestamp=timestamp, state=state):
                    if ev not in events: events.append(ev)
    # B454: Radar-vs-Radar-Dedup pro Frame -- eine cell_id darf im selben Frame
    # nur von genau EINEM lebenden Radar-Objekt getragen werden.
    for ev in _dedupe_frame_cell_ids(radar_objects or [], state, timestamp=timestamp):
        events.append(ev)
    save_lineage_state(state)
    return events
