"""Persistente Admin-Overrides fuer Hydro-Stationen.

Die Datei liegt bewusst ausserhalb generierter Hydro-Indizes, damit Aktivierungen
Neustarts, install.sh und Static-Rebuilds ueberstehen.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
from typing import Any

import config

DEFAULT_PATH = Path(getattr(config, "HYDRO_STATION_OVERRIDES_PATH", "data/config/hydro_station_overrides.json"))


def path() -> Path:
    return Path(os.environ.get("HYDRO_STATION_OVERRIDES_PATH", str(DEFAULT_PATH)))


def load() -> dict[str, dict[str, Any]]:
    p = path()
    try:
        with p.open("r", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                data = json.load(f)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except FileNotFoundError:
        return {}
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for sid, override in data.items():
        if isinstance(override, dict):
            clean = {k: v for k, v in override.items() if k in {"enabled", "default_lag_min", "estimated_lag_min", "mark_q_m3s"}}
            if "enabled" in clean:
                clean["enabled"] = bool(clean["enabled"])
            out[str(sid)] = clean
    return out


def save(overrides: dict[str, dict[str, Any]]) -> None:
    p = path(); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            json.dump(overrides, f, indent=2, ensure_ascii=False)
            f.write("\n"); f.flush(); os.fsync(f.fileno())
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    os.replace(tmp, p)


def patch_station(station_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    overrides = load()
    cur = dict(overrides.get(str(station_id), {}))
    for k, v in patch.items():
        if v is None and k in {"mark_q_m3s"}:
            cur.pop(k, None)
        else:
            cur[k] = v
    overrides[str(station_id)] = cur
    save(overrides)
    return cur
