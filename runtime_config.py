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
_LAST_LOAD_ERROR: str | None = None   # P2-2: letzter Ladefehler aus _load()


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
    """Liest runtime_overrides.json mit Shared File-Lock (Cross-Process-sicher).
    P2-2: Ladefehler werden in _LAST_LOAD_ERROR gespeichert und geloggt statt still
    verworfen, damit der Admin über Config-Probleme informiert wird."""
    global _LAST_LOAD_ERROR
    path = _get_path()
    if not os.path.exists(path):
        _LAST_LOAD_ERROR = None
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_SH)   # Shared Lock: parallele Leser OK
            try:
                data = json.load(f)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        _LAST_LOAD_ERROR = None
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError as _exc:
        _LAST_LOAD_ERROR = f"JSON-Fehler in {path}: {_exc}"
        try:
            from debug_utils import debug_log as _dlog
            _dlog(f"[CONFIG] P2-2: {_LAST_LOAD_ERROR} — System nutzt Defaults")
        except Exception:
            pass
        return {}
    except Exception as _exc:
        _LAST_LOAD_ERROR = f"Ladefehler {path}: {type(_exc).__name__}: {_exc}"
        try:
            from debug_utils import debug_log as _dlog
            _dlog(f"[CONFIG] P2-2: {_LAST_LOAD_ERROR} — System nutzt Defaults")
        except Exception:
            pass
        return {}


def get_load_error() -> str | None:
    """P2-2: Liefert den letzten Ladefehler aus runtime_overrides.json oder None."""
    return _LAST_LOAD_ERROR


def reload_overrides() -> None:
    """Lädt runtime_overrides.json neu in den In-Memory-Cache."""
    global _OVERRIDES
    with _LOCK:
        _OVERRIDES = _load()



def _location_key(entry: Any) -> str:
    if not isinstance(entry, dict):
        return ""
    return str(entry.get("name", "")).strip().casefold()


def merge_locations_watchlist(user_locations: Any = None) -> list:
    """Effective watchlist: user entries first, missing config defaults appended by name."""
    defaults = getattr(_cfg, "LOCATIONS_WATCHLIST", [])
    with _LOCK:
        if user_locations is None:
            user_locations = _OVERRIDES.get("LOCATIONS_WATCHLIST", defaults)
    base = user_locations if isinstance(user_locations, list) else []
    merged = [dict(x) if isinstance(x, dict) else x for x in base]
    seen = {_location_key(x) for x in merged if _location_key(x)}
    for loc in defaults if isinstance(defaults, list) else []:
        key = _location_key(loc)
        if key and key not in seen:
            merged.append(dict(loc))
            seen.add(key)
    return merged

def get(name: str, default: Any = None) -> Any:
    """Override > Config > default; LOCATIONS_WATCHLIST is default-merged by name."""
    if name == "LOCATIONS_WATCHLIST":
        return merge_locations_watchlist()
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
    out["LOCATIONS_WATCHLIST"] = merge_locations_watchlist()
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


# P1-4: Schlüssel, die NIEMALS über runtime_overrides.json überschrieben werden dürfen.
# - UPSCALE_FACTOR definiert das Koordinatensystem aller gespeicherten JSON-Objekte;
#   eine Laufzeitänderung korrumpiert alle gespeicherten Objekt-Koordinaten.
# - Secrets (Token/Keys/Passwörter) gehören ausschließlich in .env.
_FORBIDDEN_OVERRIDE_KEYS = frozenset({
    "UPSCALE_FACTOR",
    "GITHUB_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_KEY",
})
_FORBIDDEN_KEY_SUBSTRINGS = (
    "TOKEN", "SECRET", "PASSWORD", "PASSWD", "APIKEY", "API_KEY", "PRIVATE_KEY",
)
# B119: Schlüssel die einen verbotenen Substring enthalten, aber KEINE Secrets sind.
# max_tokens / max_tokens_per_chunk sind numerische API-Limits, keine Auth-Token.
# Ohne Allowlist streicht patch() AI_ANALYSIS_CONFIG still (200 OK, nichts gespeichert).
_FORBIDDEN_KEY_ALLOWLIST = frozenset({
    "MAX_TOKENS",
    "MAX_TOKENS_PER_CHUNK",
})


# B286: Qualitätsziele <=30 Min sind laut zieldefinition.txt fest und dürfen
# nicht per Runtime-Override gelockert werden — numerisch geprüft, damit auch
# benutzerdefinierte Horizonte (z.B. h15/h25 via /api/horizons) korrekt erfasst
# werden, nicht nur die Standardwerte 10/20/30.
_QUALITY_TARGET_KEY_PREFIX = "QUALITY_TARGET_MAE_KM_"


def _quality_target_horizon_from_key(ku: str) -> int | None:
    if not ku.startswith(_QUALITY_TARGET_KEY_PREFIX):
        return None
    suffix = ku[len(_QUALITY_TARGET_KEY_PREFIX):]
    try:
        return int(suffix)
    except ValueError:
        return None


def validate_override_key(key: str) -> None:
    ku = str(key).upper()
    horizon = _quality_target_horizon_from_key(ku)
    if horizon is not None:
        if horizon <= 30:
            raise ValueError(
                f"{ku} ist durch zieldefinition.txt fest vorgegeben (<=30 Min, <1km) und nicht überschreibbar"
            )
        return
    if ku.startswith(_QUALITY_TARGET_KEY_PREFIX):
        raise ValueError(f"{ku} ist kein administrierbares Qualitätsziel")


_HYDRO_NUMERIC_LIMITS = {
    "HYDRO_FORECAST_SAMPLE_STEP_MIN": (1, 10),
    "HYDRO_FALLBACK_ROUTING_TAU_MIN": (0, 1440),
    "HYDRO_FORECAST_RUNOFF_COEFF": (0, 1),
    "HYDRO_FORECAST_ROUTING_ATTENUATION": (0, 1),
    "HYDRO_MIN_OVERLAP_AREA_KM2": (0, None),
    "HYDRO_MIN_OVERLAP_RATIO_CELL": (0, 1),
}

def validate_override_value(key: str, value) -> None:
    ku = str(key).upper()
    if ku not in _HYDRO_NUMERIC_LIMITS:
        return
    lo, hi = _HYDRO_NUMERIC_LIMITS[ku]
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{ku} muss numerisch sein")
    if ku == "HYDRO_FALLBACK_ROUTING_TAU_MIN":
        if not (num > 0 and num <= 1440):
            raise ValueError(f"{ku} muss > 0 und <= 1440 sein")
        return
    if num < lo or (hi is not None and num > hi):
        raise ValueError(f"{ku} muss im Bereich {lo}..{hi} liegen")

def set_override(key: str, value) -> dict:
    validate_override_key(key)
    validate_override_value(key, value)
    return patch({key: value})


def is_forbidden_override_key(key) -> bool:
    """True wenn key nicht als Runtime-Override zulässig ist (P1-4).

    B119: _FORBIDDEN_KEY_ALLOWLIST schützt numerische Limits vor False Positives.
    Erlaubte Keys werden VOR der Substring-Prüfung freigestellt.
    """
    ku = str(key).upper()
    if ku in _FORBIDDEN_KEY_ALLOWLIST:
        return False          # B119: numerisches Limit — nie blockieren
    if ku in _FORBIDDEN_OVERRIDE_KEYS:
        return True
    return any(tok in ku for tok in _FORBIDDEN_KEY_SUBSTRINGS)


def is_editable_override_key(key) -> bool:
    """B352: True wenn `key` grundsaetzlich als Top-Level-Runtime-Override
    akzeptiert werden KOENNTE (unabhaengig vom konkreten Wert) — d.h. weder
    is_forbidden_override_key() noch validate_override_key() wuerden ihn
    ablehnen. Genutzt von GET /api/config, damit die Admin-UI keine Schluessel
    zum Bearbeiten anzeigt, die beim Zurueckspeichern des unveraenderten
    Gesamtstands ohnehin abgelehnt wuerden (z.B. QUALITY_TARGET_MAE_KM_FIXED,
    QUALITY_TARGET_MAE_KM_CONFIGURABLE_DEFAULT, UPSCALE_FACTOR)."""
    if is_forbidden_override_key(key):
        return False
    try:
        validate_override_key(key)
    except ValueError:
        return False
    return True


def _find_forbidden_paths(obj, prefix: str = "") -> list:
    """
    B106: Rekursiv alle verbotenen Schlüsselpfade in obj finden.
    Gibt Pfade wie 'GITHUB_VERIFY_CONFIG.token' zurück.
    """
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            if is_forbidden_override_key(k):
                found.append(path)
            found.extend(_find_forbidden_paths(v, path))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found.extend(_find_forbidden_paths(v, f"{prefix}[{i}]"))
    return found


def _strip_forbidden_keys(obj):
    """Entfernt verbotene Schlüssel rekursiv vor dem Persistieren."""
    if isinstance(obj, dict):
        cleaned = {}
        for k, v in obj.items():
            if is_forbidden_override_key(k):
                continue
            cleaned[k] = _strip_forbidden_keys(v)
        return cleaned
    if isinstance(obj, list):
        return [_strip_forbidden_keys(v) for v in obj]
    return obj


def strip_forbidden_recursive(obj):
    """B352: Oeffentlicher Wrapper um _strip_forbidden_keys() fuer Aufrufer
    ausserhalb dieses Moduls (z.B. GET /api/config in app.py). Entfernt
    verbotene Schluessel (auch verschachtelt, z.B. GITHUB_VERIFY_CONFIG.token)
    VOLLSTAENDIG, statt sie nur zu redigieren — damit ein unveraendert
    zurueckgeposteter GET-Response nie an B106/B351 scheitert."""
    return _strip_forbidden_keys(obj)


def forbidden_keys_in(partial: dict) -> list:
    """
    Liefert alle verbotenen Schlüsselpfade aus partial (Top-Level und verschachtelt).
    B106: Rekursive Prüfung — verhindert Secrets in nested Objekten wie
    GITHUB_VERIFY_CONFIG.token oder AI_ANALYSIS_CONFIG.api_key.
    """
    if not isinstance(partial, dict):
        return []
    return sorted(_find_forbidden_paths(partial))


def patch_exact_key(top_key: str, value) -> dict:
    """B244: Ersetzt einen Top-Level-Schlüssel vollständig ohne _deep_merge.
    Verwenden statt patch() wenn ein verschachteltes Dict komplett neu gesetzt
    werden soll und _deep_merge das Löschen von Unter-Schlüsseln verhindern würde
    (z. B. Löschen von mark_q_m3s in HYDRO_STATION_OVERRIDES[sid]).

    B362: Laedt den Stand unmittelbar vor dem Merge frisch von der Platte.
    wetterprojekt/wetterprojekt-scheduler/wetterprojekt-admin laufen als
    unabhaengige Prozesse mit je eigenem In-Memory-Cache (_OVERRIDES) — ohne
    diesen Reload wuerde ein veralteter Cache-Stand beim naechsten save()
    zwischenzeitliche Schreibvorgaenge ANDERER Prozesse lautlos ueberschreiben
    (siehe Analyse zum LOCATIONS_WATCHLIST-Datenverlust)."""
    validate_override_key(top_key)
    if is_forbidden_override_key(top_key):
        reload_overrides()
        return dict(_OVERRIDES)
    reload_overrides()
    with _LOCK:
        merged = dict(_OVERRIDES)
        merged[top_key] = _strip_forbidden_keys(value) if isinstance(value, (dict, list)) else value
        # Defense-in-depth: auch bereits vorhandene Alt-Overrides bereinigen,
        # damit Stations-Patches keine bestehenden Secrets erneut persistieren.
        merged = _strip_forbidden_keys(merged)
    save(merged)
    return merged


def patch(partial: dict) -> dict:
    """Mergt partial in bestehende Overrides und persistiert.

    P1-4/B106: Verbotene Schlüssel (UPSCALE_FACTOR, Secrets, auch verschachtelt)
    werden defensiv entfernt. Defense-in-Depth: patch() bereinigt unabhängig vom
    aufrufenden Endpunkt. Die öffentliche API (/api/config) lehnt bei verbotenen
    Pfaden mit HTTP 400 ab (vor patch()-Aufruf).

    B362: Laedt den Stand unmittelbar vor dem Merge frisch von der Platte
    (reload_overrides()), statt sich auf den moeglicherweise veralteten
    In-Memory-Cache des aufrufenden Prozesses zu verlassen. Ohne diesen
    Reload konnte ein Prozess (z. B. wetterprojekt-admin waehrend eines
    Trainingslaufs, training_control.py) beim naechsten patch()-Aufruf
    fuer einen VOELLIG ANDEREN Key zwischenzeitliche Schreibvorgaenge eines
    ANDEREN Prozesses (z. B. LOCATIONS_WATCHLIST-Speicherung ueber das Admin
    Panel) lautlos überschreiben — siehe Analyse zum beobachteten
    Datenverlust.
    """
    reload_overrides()
    if isinstance(partial, dict):
        for _key, _value in partial.items():
            validate_override_key(_key)
            validate_override_value(_key, _value)
        _forbidden = forbidden_keys_in(partial)
        if _forbidden:
            # B106: Gesamte Anfrage defensiv ablehnen wenn verbotene Pfade vorhanden.
            # Top-Level-Keys entfernen deren Unterpfade verboten sind.
            _forbidden_top = {p.split(".")[0].split("[")[0] for p in _forbidden}
            partial = {k: v for k, v in partial.items() if k not in _forbidden_top}
    with _LOCK:
        merged = _strip_forbidden_keys(_deep_merge(_OVERRIDES, partial))
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
