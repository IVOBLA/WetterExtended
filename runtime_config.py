import json
import os
import threading
from typing import Any
import config as _cfg

_LOCK = threading.RLock()
_OVERRIDES: dict = {}


def _load() -> dict:
    path = getattr(_cfg, "RUNTIME_OVERRIDES_PATH", "train_data/runtime_overrides.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def reload_overrides() -> None:
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
    """Schreibt Overrides atomar zurück und reloaded."""
    path = getattr(_cfg, "RUNTIME_OVERRIDES_PATH", "train_data/runtime_overrides.json")
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(overrides, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
    reload_overrides()


def patch(partial: dict) -> dict:
    """Mergt partial in bestehende Overrides und persistiert."""
    with _LOCK:
        merged = dict(_OVERRIDES)
    merged.update(partial)
    save(merged)
    return merged


reload_overrides()
