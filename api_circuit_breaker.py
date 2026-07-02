"""Thread-sicherer Circuit-Breaker für externe API-Services."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path

try:
    from debug_utils import debug_log
except Exception:  # pragma: no cover - erlaubt Circuit-Tests ohne optionale Runtime-Dependencies
    def debug_log(message):
        print(message)

STATE_FILE = Path(os.getenv("API_CIRCUIT_BREAKER_FILE", "train_data/system/api_circuit_breaker.json"))
CIRCUIT_COOLDOWN_429 = int(os.getenv("CIRCUIT_COOLDOWN_429", "3600"))
CIRCUIT_COOLDOWN_5XX = int(os.getenv("CIRCUIT_COOLDOWN_5XX", "1800"))
CIRCUIT_COOLDOWN_CONN = int(os.getenv("CIRCUIT_COOLDOWN_CONN", "900"))
CIRCUIT_THRESHOLD_5XX = int(os.getenv("CIRCUIT_THRESHOLD_5XX", "3"))
CIRCUIT_THRESHOLD_CONN = int(os.getenv("CIRCUIT_THRESHOLD_CONN", "4"))

# B281: exponentieller Backoff für wiederholt fehlschlagende Quellen.
CIRCUIT_BACKOFF_BASE_S = int(os.getenv("CIRCUIT_BACKOFF_BASE_S", str(15 * 60)))       # 15 Min Start
CIRCUIT_BACKOFF_FACTOR = float(os.getenv("CIRCUIT_BACKOFF_FACTOR", "2.0"))
CIRCUIT_BACKOFF_MAX_S = int(os.getenv("CIRCUIT_BACKOFF_MAX_S", str(12 * 3600)))       # 12h Obergrenze
CIRCUIT_SUSPEND_AFTER_STREAK = int(os.getenv("CIRCUIT_SUSPEND_AFTER_STREAK", "6"))
CIRCUIT_SUSPEND_DURATION_S = int(os.getenv("CIRCUIT_SUSPEND_DURATION_S", str(24 * 3600)))

_LOCK = threading.RLock()
_STATE: dict[str, dict] = {}


def _load() -> None:
    global _STATE
    try:
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            _STATE = data if isinstance(data, dict) else {}
    except Exception as exc:
        debug_log(f"[CIRCUIT] State konnte nicht geladen werden: {exc}")
        _STATE = {}


def _save() -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="api_circuit_", suffix=".json", dir=str(STATE_FILE.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(_STATE, f, ensure_ascii=False, indent=2)
        os.replace(name, STATE_FILE)
    finally:
        try:
            if os.path.exists(name):
                os.unlink(name)
        except Exception:
            pass


def _now() -> float:
    # B144: WALL-CLOCK statt time.monotonic(). cooldown_until wird auf Platte persistiert
    # und nach Prozess-Neustart/Reboot mit _now() verglichen. monotonic() ist über Reboots
    # NICHT vergleichbar (resettet) → der Breaker blieb dauerhaft offen
    # (open_meteo_atmosphere → atmospheric_snapshot dauerhaft übersprungen → openmeteo
    # "fällig"/leer). time.time() ist über Neustarts gültig; alte stuck-open-Zustände
    # heilen sich beim ersten is_open()-Aufruf selbst.
    return time.time()


def _entry(service_name: str) -> dict:
    e = _STATE.setdefault(service_name, {
        "open": False, "failures_5xx": 0, "failures_conn": 0,
        "failure_streak": 0, "last_success_at": None, "last_failure_at": None,
        "cooldown_until": None, "cooldown_level": 0, "suspended_until": None,
        "last_error_class": None,
    })
    e.setdefault("failure_streak", 0)
    e.setdefault("last_success_at", None)
    e.setdefault("last_failure_at", None)
    e.setdefault("cooldown_until", None)
    e.setdefault("cooldown_level", 0)
    e.setdefault("suspended_until", None)
    e.setdefault("last_error_class", None)
    return e


def is_open(service_name: str) -> bool:
    with _LOCK:
        e = _entry(service_name)
        suspended_until = e.get("suspended_until")
        if suspended_until is not None and _now() < float(suspended_until):
            return True
        until = e.get("cooldown_until")
        if e.get("open") and until is not None and _now() > float(until):
            e.update({"open": False, "failures_5xx": 0, "failures_conn": 0, "reason": None, "cooldown_until": None, "logged_open": False})
            _save()
            return False
        return bool(e.get("open"))


def get_status(service_name: str) -> dict:
    with _LOCK:
        is_open(service_name)
        return dict(_entry(service_name))


def record_success(service_name: str) -> None:
    with _LOCK:
        _STATE[service_name] = {
            "open": False, "failures_5xx": 0, "failures_conn": 0, "reason": None,
            "cooldown_until": None, "logged_open": False,
            "failure_streak": 0, "last_success_at": _now(), "last_failure_at": _STATE.get(service_name, {}).get("last_failure_at"),
            "cooldown_level": 0, "suspended_until": None, "last_error_class": None,
        }
        _save()


def open_circuit(service_name: str, cooldown_seconds: int, reason: str) -> None:
    with _LOCK:
        e = _entry(service_name)
        was_open = bool(e.get("open"))
        e.update({
            "open": True,
            "reason": reason,
            "cooldown_seconds": int(cooldown_seconds),
            "cooldown_until": _now() + int(cooldown_seconds),
            "opened_at": time.time(),
        })
        if not was_open:
            debug_log(f"[CIRCUIT] {service_name} geöffnet reason={reason} cooldown={cooldown_seconds}s")
        _save()


def _backoff_cooldown_s(cooldown_level: int) -> int:
    """B281: exponentieller Backoff, gedeckelt auf CIRCUIT_BACKOFF_MAX_S."""
    raw = CIRCUIT_BACKOFF_BASE_S * (CIRCUIT_BACKOFF_FACTOR ** max(0, cooldown_level))
    return int(min(raw, CIRCUIT_BACKOFF_MAX_S))


def record_failure(service_name: str, reason: str, http_status: int | None = None, retry_after: int | None = None) -> None:
    if http_status == 429:
        open_circuit(service_name, int(retry_after or CIRCUIT_COOLDOWN_429), reason or "http-429")
        return
    with _LOCK:
        e = _entry(service_name)
        e["failure_streak"] = int(e.get("failure_streak", 0)) + 1
        e["last_failure_at"] = _now()
        e["last_error_class"] = reason
        if http_status in (502, 503, 504):
            e["failures_5xx"] = int(e.get("failures_5xx", 0)) + 1
            should_open = e["failures_5xx"] >= CIRCUIT_THRESHOLD_5XX
        elif reason in {"SSLError", "Timeout", "ConnectionError", "timeout", "ssl", "connection"}:
            e["failures_conn"] = int(e.get("failures_conn", 0)) + 1
            should_open = e["failures_conn"] >= CIRCUIT_THRESHOLD_CONN
        else:
            should_open = False
        cooldown_level = int(e.get("cooldown_level", 0))
        cooldown = _backoff_cooldown_s(cooldown_level)
        if should_open:
            e["cooldown_level"] = cooldown_level + 1
        if e["failure_streak"] >= CIRCUIT_SUSPEND_AFTER_STREAK:
            e["suspended_until"] = _now() + CIRCUIT_SUSPEND_DURATION_S
            debug_log(f"[CIRCUIT][B281] {service_name} nach {e['failure_streak']} Folgefehlern für {CIRCUIT_SUSPEND_DURATION_S}s suspendiert")
        _save()
    if should_open:
        open_circuit(service_name, cooldown, reason)


def cooldown_until(service_name: str) -> float | None:
    with _LOCK:
        val = _entry(service_name).get("cooldown_until")
        return float(val) if val is not None else None


def reset(service_name: str) -> None:
    with _LOCK:
        _STATE.pop(service_name, None)
        _save()


_load()
