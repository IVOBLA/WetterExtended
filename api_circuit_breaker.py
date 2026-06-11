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
    return time.monotonic()


def _entry(service_name: str) -> dict:
    return _STATE.setdefault(service_name, {"open": False, "failures_5xx": 0, "failures_conn": 0})


def is_open(service_name: str) -> bool:
    with _LOCK:
        e = _entry(service_name)
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
        _STATE[service_name] = {"open": False, "failures_5xx": 0, "failures_conn": 0, "reason": None, "cooldown_until": None, "logged_open": False}
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


def record_failure(service_name: str, reason: str, http_status: int | None = None, retry_after: int | None = None) -> None:
    if http_status == 429:
        open_circuit(service_name, int(retry_after or CIRCUIT_COOLDOWN_429), reason or "http-429")
        return
    with _LOCK:
        e = _entry(service_name)
        if http_status in (502, 503, 504):
            e["failures_5xx"] = int(e.get("failures_5xx", 0)) + 1
            should_open = e["failures_5xx"] >= CIRCUIT_THRESHOLD_5XX
            cooldown = CIRCUIT_COOLDOWN_5XX
        elif reason in {"SSLError", "Timeout", "ConnectionError", "timeout", "ssl", "connection"}:
            e["failures_conn"] = int(e.get("failures_conn", 0)) + 1
            should_open = e["failures_conn"] >= CIRCUIT_THRESHOLD_CONN
            cooldown = CIRCUIT_COOLDOWN_CONN
        else:
            should_open = False
            cooldown = CIRCUIT_COOLDOWN_CONN
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
