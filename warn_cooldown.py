"""B441: Persistenter, ortsbasierter Warn-Cooldown.

Der bisherige Warnschutz war an die cell_id gekoppelt (umgehbar, weil cell_ids bei
Merge/Split/Reaktivierung wechseln) und lag nur im RAM (nicht neustartfest). Dieses
Modul führt einen Cooldown pro Ort, unabhängig von der cell_id, persistent auf Platte.
Es greift in main.py vor dem Versand über beide Kanäle.
"""
from __future__ import annotations

import json
import os
import time
from typing import Iterable

try:
    from debug_utils import debug_log  # type: ignore
except Exception:  # pragma: no cover
    def debug_log(*_a, **_k):
        pass

_COOLDOWN_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "train_data", "evaluation", "warn_cooldown.json",
)


def _default_cooldown_s() -> int:
    """WARN_COOLDOWN_S aus runtime_config, sonst config, sonst 900."""
    try:
        import runtime_config
        from config import WARN_COOLDOWN_S as _def
        return int(runtime_config.get("WARN_COOLDOWN_S", _def))
    except Exception:
        try:
            from config import WARN_COOLDOWN_S as _def2
            return int(_def2)
        except Exception:
            return 900


def _read() -> dict:
    try:
        if os.path.exists(_COOLDOWN_FILE):
            with open(_COOLDOWN_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                # nur numerische Werte behalten (robust gegen Fremdinhalt)
                return {str(k): float(v) for k, v in data.items()
                        if isinstance(v, (int, float))}
    except Exception as exc:
        debug_log(f"[WARN-CD] Lesefehler {_COOLDOWN_FILE}: {exc}")
    return {}


def _write(state: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_COOLDOWN_FILE), exist_ok=True)
        tmp = _COOLDOWN_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        os.replace(tmp, _COOLDOWN_FILE)
    except Exception as exc:
        debug_log(f"[WARN-CD] Schreibfehler {_COOLDOWN_FILE}: {exc}")


def is_blocked(loc_name: str, now: float | None = None) -> bool:
    """True, wenn für loc_name der Cooldown noch aktiv ist."""
    now = time.time() if now is None else now
    cd = _default_cooldown_s()
    last = _read().get(str(loc_name), 0.0)
    return (now - last) < cd


def filter_allowed(loc_names: Iterable[str], now: float | None = None) -> set[str]:
    """Gibt die Teilmenge zurück, die NICHT im Cooldown ist (darf warnen)."""
    now = time.time() if now is None else now
    cd = _default_cooldown_s()
    state = _read()
    allowed = set()
    for name in loc_names:
        last = state.get(str(name), 0.0)
        if (now - last) >= cd:
            allowed.add(str(name))
        else:
            debug_log(
                f"[WARN-CD] {name}: Cooldown aktiv "
                f"({int((cd - (now - last)) / 60)} min verbleibend) — Alarm unterdrückt."
            )
    return allowed


def mark_sent(loc_name: str, now: float | None = None) -> None:
    """Merkt den Sendezeitpunkt für loc_name persistent."""
    now = time.time() if now is None else now
    state = _read()
    state[str(loc_name)] = now
    _write(state)
