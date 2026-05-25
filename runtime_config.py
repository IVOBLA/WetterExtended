# runtime_config.py
"""
Laufzeit-Konfiguration für WetterExtended.

Liest Overrides aus train_data/runtime_overrides.json (gitignored).
Override > Config-Default > übergegebener Default.

Thread-Safety: threading.RLock (innerhalb eines Prozesses)
File-Safety:   fcntl.flock   (zwischen den 3 Service-Prozessen)
"""

import fcntl
import json
import os
import threading
from typing import Any

import config as _cfg

_LOCK = threading.RLock()
_OVERRIDES: dict = {}


def _get_path() -> str:
    return getattr(_cfg, "RUNTIME_OVERRIDES_PATH", "train_data/runtime_overrides.json")


def _deep_merge(base: dict, patch_data: dict) -> dict:
    merged = dict(base)
    for key, value in patch_data.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load() -> dict:
    """Liest runtime_overrides.json mit Shared File-Lock (Cross-Process-sicher)."""
    path = _get_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_SH)   # Shared Lock: parallele Leser OK
            try:
                data = json.load(f)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def reload_overrides() -> None:
    """Lädt runtime_overrides.json neu in den In-Memory-Cache."""
    global _OVERRIDES
    with _LOCK:
        _OVERRIDES = _load()


def get(name: str, default: Any = None) -> Any:
    """Override > Config > default."""
    with _LOCK:
        if name in _OVERRIDES:
            return _OVERRIDES[name]
    return getattr(_cfg, name, default)


def all_effective() -> dict:
    """Alle effektiven Konfig-Werte als Dict (Config-Defaults + Overrides)."""
    out = {}
    for k in dir(_cfg):
        if k.startswith("_"):
            continue
        v = getattr(_cfg, k)
        if callable(v):
            continue
        if isinstance(v, (int, float, str, bool, list, dict, tuple)):
            out[k] = v
    with _LOCK:
        for k, v in _OVERRIDES.items():
            out[k] = v
    return out


def save(overrides: dict) -> None:
    """
    Schreibt Overrides atomar zurück.
    P35: Sichert aktuellen Stand als .bak vor dem Überschreiben (für rollback()).
    """
    path = _get_path()
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    bak = path + ".bak"

    with _LOCK:
        # P35: Backup des aktuellen Stands (einmalig pro Schreibvorgang)
        if os.path.exists(path):
            try:
                import shutil as _shutil
                _shutil.copy2(path, bak)
            except Exception:
                pass
        with open(tmp, "w", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)   # Exclusive Lock: nur ein Schreiber
            try:
                json.dump(overrides, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())         # Auf Raspbian SD-Karte wichtig
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        os.replace(tmp, path)  # atomic auf Linux
    reload_overrides()


def patch(partial: dict) -> dict:
    """Mergt partial in bestehende Overrides und persistiert."""
    with _LOCK:
        merged = _deep_merge(_OVERRIDES, partial)
    save(merged)
    return merged


def rollback() -> dict:
    """
    P35: Setzt runtime_overrides.json auf den Stand vor dem letzten patch()-Aufruf zurück.
    Gibt die wiederhergestellten Overrides zurück, oder {} wenn kein Backup vorhanden.
    """
    path = _get_path()
    bak = path + ".bak"
    if not os.path.exists(bak):
        return {}
    try:
        with open(bak, "r", encoding="utf-8") as f:
            previous = json.load(f)
        tmp = path + ".tmp"
        with _LOCK:
            with open(tmp, "w", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    json.dump(previous, f, indent=2, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
            os.replace(tmp, path)
        reload_overrides()
        return previous
    except Exception as exc:
        return {"error": str(exc)}


# Beim Modulimport einmalig laden
reload_overrides()
