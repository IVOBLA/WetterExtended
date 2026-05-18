# api_cache.py
"""
Zentraler TTL-basierter Cache für externe API-Responses.

Vermeidet redundante Requests an Open-Meteo, GeoSphere, EUMETView,
Blitzortung etc. wenn deren Daten in der Zwischenzeit gar nicht
aktualisiert wurden (Update-Intervalle der Anbieter).

Cache liegt unter train_data/api_cache/ als JSON-Dateien (persistiert über
Neustarts). TTL-Werte konfigurierbar über config.API_CACHE_TTL_SECONDS und
runtime_overrides.json.

Verwendung:
    from api_cache import cache_get, cache_set, cache_key, get_ttl

    key = cache_key("openmeteo:icon_d2", coord_list, target_hour)
    data = cache_get(key, ttl_seconds=get_ttl("openmeteo_icon_d2", 1800))
    if data is None:
        data = requests.get(url, timeout=15).json()
        cache_set(key, data)
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any

from debug_utils import debug_log

try:
    from config import SAVE_PATHS as _SP
    _CACHE_DIR = os.path.join(
        _SP.get("evaluation", "train_data/evaluation/").rstrip("/"),
        "..", "api_cache"
    )
    _CACHE_DIR = os.path.normpath(_CACHE_DIR)
except Exception:
    _CACHE_DIR = "train_data/api_cache"

# In-Memory-LRU für schnelle wiederholte Zugriffe innerhalb eines Prozesses
_MEM_CACHE: dict[str, tuple[float, Any]] = {}
_MEM_CACHE_MAX = 64


def _ensure_dir() -> None:
    os.makedirs(_CACHE_DIR, exist_ok=True)


def cache_key(namespace: str, *components: Any, grid_round_deg: float | None = None) -> str:
    """
    Erzeugt einen stabilen Cache-Schlüssel.
    - namespace: z.B. "openmeteo:icon_d2"
    - components: alles was den Request charakterisiert (Koordinatenliste,
      Zielzeit, BBox …). Listen von (lat, lon) werden auf grid_round_deg
      gerundet (default 0,02° ≈ 2 km bei 47° N), damit kleine Zellbewegungen
      denselben Cache-Eintrag treffen.
    """
    if grid_round_deg is None:
        try:
            from config import API_CACHE_GRID_ROUND_DEG
            grid_round_deg = API_CACHE_GRID_ROUND_DEG
        except Exception:
            grid_round_deg = 0.02

    parts: list[str] = [namespace]
    for c in components:
        if isinstance(c, (list, tuple)) and c and isinstance(c[0], (list, tuple)):
            # Koordinatenliste [(lat,lon), ...]
            rounded = sorted(
                (round(lat / grid_round_deg) * grid_round_deg,
                 round(lon / grid_round_deg) * grid_round_deg)
                for lat, lon in c
            )
            parts.append(json.dumps(rounded, separators=(",", ":")))
        else:
            parts.append(str(c))
    raw = "|".join(parts)
    digest = hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]
    safe_ns = namespace.replace(":", "_").replace("/", "_")
    return f"{safe_ns}_{digest}"


def _path_for(key: str) -> str:
    return os.path.join(_CACHE_DIR, f"{key}.json")


def cache_get(key: str, ttl_seconds: int) -> Any | None:
    """
    Liefert den Cache-Eintrag wenn er existiert UND nicht älter als ttl_seconds ist.
    Sonst None.
    """
    # 1) In-Memory
    rec = _MEM_CACHE.get(key)
    if rec is not None:
        ts, value = rec
        if time.time() - ts <= ttl_seconds:
            debug_log(f"[API-CACHE] HIT (mem) {key} age={int(time.time()-ts)}s")
            return value
        else:
            _MEM_CACHE.pop(key, None)

    # 2) Disk
    path = _path_for(key)
    if not os.path.exists(path):
        return None
    try:
        st = os.stat(path)
        age = time.time() - st.st_mtime
        if age > ttl_seconds:
            debug_log(f"[API-CACHE] EXPIRED {key} age={int(age)}s ttl={ttl_seconds}s")
            return None
        with open(path, "r", encoding="utf-8") as f:
            value = json.load(f)
        _put_mem(key, value)
        debug_log(f"[API-CACHE] HIT (disk) {key} age={int(age)}s")
        return value
    except Exception as exc:
        debug_log(f"[API-CACHE] Lesefehler {key}: {exc}")
        return None


def cache_set(key: str, value: Any) -> None:
    """Schreibt den Eintrag in Memory + Disk."""
    _put_mem(key, value)
    _ensure_dir()
    path = _path_for(key)
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False)
        os.replace(tmp, path)
        debug_log(f"[API-CACHE] STORE {key}")
    except Exception as exc:
        debug_log(f"[API-CACHE] Schreibfehler {key}: {exc}")


def _put_mem(key: str, value: Any) -> None:
    if len(_MEM_CACHE) >= _MEM_CACHE_MAX:
        oldest = min(_MEM_CACHE.items(), key=lambda kv: kv[1][0])[0]
        _MEM_CACHE.pop(oldest, None)
    _MEM_CACHE[key] = (time.time(), value)


def cache_invalidate(key: str) -> None:
    _MEM_CACHE.pop(key, None)
    path = _path_for(key)
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass


def cache_cleanup(max_age_seconds: int = 7 * 24 * 3600) -> int:
    """Räumt Cache-Dateien älter als max_age_seconds auf."""
    if not os.path.isdir(_CACHE_DIR):
        return 0
    n = 0
    now = time.time()
    for name in os.listdir(_CACHE_DIR):
        path = os.path.join(_CACHE_DIR, name)
        try:
            if now - os.path.getmtime(path) > max_age_seconds:
                os.remove(path)
                n += 1
        except Exception:
            continue
    return n


def get_ttl(name: str, default: int) -> int:
    """Liest TTL aus runtime_config mit Fallback auf config.API_CACHE_TTL_SECONDS."""
    try:
        import runtime_config
        from config import API_CACHE_TTL_SECONDS
        ttls = runtime_config.get("API_CACHE_TTL_SECONDS", API_CACHE_TTL_SECONDS)
        return int(ttls.get(name, default))
    except Exception:
        return default
