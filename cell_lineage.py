"""Persistente Zell-Lineage-IDs für IR-Vorläuferzellen.

1L.1 vergibt stabile fachliche ``cell_id`` Werte für CB-IR-Tracks. Radar-
Übernahme und Score-Matching werden nur im State vorbereitet und noch nicht aktiv
umgesetzt.
"""

from __future__ import annotations

import json
import os
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
    )
except Exception:  # pragma: no cover
    CELL_ID_PREFIX = "WX"
    CELL_LINEAGE_STATE_DIR = "train_data/cell_lineage"
    CELL_LINEAGE_STATE_FILE = "cell_lineage_state.json"
    CELL_LINEAGE_EVENTS_FILE = "cell_lineage_events.jsonl"


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


def _empty_state() -> dict:
    return {"version": 1, "date_counters": {}, "ir_to_cell": {}, "radar_to_cell": {}, "cells": {}}


def _normalize_state(state: dict | None) -> dict:
    if not isinstance(state, dict):
        return _empty_state()
    out = _empty_state()
    out.update(state)
    for key in ("date_counters", "ir_to_cell", "radar_to_cell", "cells"):
        if not isinstance(out.get(key), dict):
            out[key] = {}
    out["version"] = 1
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
        return _empty_state()


def save_lineage_state(state: dict) -> None:
    path = _state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(_normalize_state(state), f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except Exception as exc:
        _debug(f"[CELL-LINEAGE] State konnte nicht gespeichert werden ({path}): {exc}")


def append_lineage_event(event: dict) -> None:
    try:
        path = _events_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception as exc:
        _debug(f"[CELL-LINEAGE] Event konnte nicht geschrieben werden: {exc}")


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
    ir_track_id = str(track.get("ir_track_id") or track.get("ir_id") or track.get("id") or "").strip()
    if ir_track_id:
        track["ir_track_id"] = ir_track_id
    ts = _track_timestamp(track, timestamp)

    existing_cell_id = track.get("cell_id") or (state.get("ir_to_cell", {}).get(ir_track_id) if ir_track_id else None)
    created = False
    if existing_cell_id:
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
    return state.get("ir_to_cell", {}).get(str(ir_track_id))
