# api_budget_guard.py
"""
1E: API-Budget-Guard — persistente Tageszaehler je externer Schnittstellen-Gruppe
und harte Durchsetzung des kostenlosen Tagesbudgets.

Zweck (zieldefinition: nur kostenlose Quellen, keine unnoetigen Requests):
  - Zaehlt jeden tatsaechlich abgesetzten externen GET (zentral aus http_retry).
  - Blockt neue Requests einer Budget-Gruppe, sobald deren Tageslimit erreicht ist
    (http_retry wirft dann BudgetExceededError -> Fetcher-Fallback/Stale-Cache greift).
  - Gruppen-Modell: alle Open-Meteo-Dienste teilen EIN Tageskontingent
    (das Free-Limit von 10.000/Tag gilt providerweit, nicht je Endpoint).

Persistenz: train_data/evaluation/api_budget.json, prozess-sicher via fcntl.flock
(3 systemd-Dienste schreiben potenziell gleichzeitig). Reset taeglich um 00:00 UTC.

Budget je Gruppe aus runtime_config["API_DAILY_BUDGET"] (Default config.API_DAILY_BUDGET).
Gruppen ohne Eintrag haben KEIN Limit (over_budget == False -> rueckwaertskompatibel).
"""
import json
import os
from datetime import datetime, timezone

try:
    import fcntl  # POSIX (Raspian/Linux)
except Exception:
    fcntl = None

try:
    from debug_utils import debug_log
except Exception:
    def debug_log(message: str) -> None:
        print(message)

try:
    import runtime_config
except Exception:
    runtime_config = None

try:
    from config import SAVE_PATHS, API_DAILY_BUDGET as _CFG_BUDGET
except Exception:
    SAVE_PATHS = {}
    _CFG_BUDGET = {}

_BUDGET_FILE = os.path.join(
    SAVE_PATHS.get("evaluation", "train_data/evaluation").rstrip("/"),
    "api_budget.json",
)


def _today() -> str:
    """Aktuelles Datum (UTC) als YYYY-MM-DD. Basis fuer den Tages-Reset."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def group_for(service: str) -> str:
    """Bildet einen kanonischen Service-Namen auf seine Budget-Gruppe ab.
    Alle 'openmeteo*'-Dienste teilen das providerweite Open-Meteo-Kontingent."""
    s = (service or "").lower()
    if s.startswith("openmeteo"):
        return "openmeteo"
    return s


def _budgets() -> dict:
    """Aktuelle Budget-Konfiguration (runtime-ueberschreibbar)."""
    if runtime_config is not None:
        try:
            val = runtime_config.get("API_DAILY_BUDGET", _CFG_BUDGET)
            if isinstance(val, dict):
                return val
        except Exception:
            pass
    return dict(_CFG_BUDGET) if isinstance(_CFG_BUDGET, dict) else {}


def _reset_if_new_day(state: dict) -> dict:
    today = _today()
    if not isinstance(state, dict) or state.get("date") != today:
        state = {"date": today, "counts": {}}
    state.setdefault("counts", {})
    return state


def _load_state() -> dict:
    """Liest den Zustand read-only (kein Schreiben). Tages-Reset beruecksichtigt."""
    try:
        with open(_BUDGET_FILE, "r", encoding="utf-8") as fh:
            raw = fh.read()
        state = json.loads(raw) if raw.strip() else {}
    except Exception:
        state = {}
    return _reset_if_new_day(state)


def over_budget(service: str) -> bool:
    """True, wenn die Budget-Gruppe des Service ihr Tageslimit erreicht/ueberschritten hat.
    Gruppen ohne konfiguriertes (positives) Limit -> immer False (kein Block)."""
    grp = group_for(service)
    limit = _budgets().get(grp)
    try:
        limit = int(limit) if limit is not None else None
    except (TypeError, ValueError):
        return False
    if not limit or limit <= 0:
        return False
    cnt = int(_load_state()["counts"].get(grp, 0))
    return cnt >= limit


def record_request(service: str) -> None:
    """Zaehlt einen tatsaechlich abgesetzten Request fuer die Budget-Gruppe (prozess-sicher)."""
    grp = group_for(service)
    try:
        os.makedirs(os.path.dirname(_BUDGET_FILE) or ".", exist_ok=True)
        if not os.path.exists(_BUDGET_FILE):
            with open(_BUDGET_FILE, "w", encoding="utf-8") as _f0:
                _f0.write("")
        with open(_BUDGET_FILE, "r+", encoding="utf-8") as fh:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                try:
                    fh.seek(0)
                    raw = fh.read()
                    state = json.loads(raw) if raw.strip() else {}
                except Exception:
                    state = {}
                state = _reset_if_new_day(state)
                state["counts"][grp] = int(state["counts"].get(grp, 0)) + 1
                fh.seek(0)
                fh.truncate()
                fh.write(json.dumps(state, ensure_ascii=False))
                fh.flush()
                os.fsync(fh.fileno())
            finally:
                if fcntl is not None:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except Exception as exc:
        debug_log(f"[BUDGET] record_request fehlgeschlagen ({service}): {exc}")


def snapshot() -> dict:
    """Zustand fuer Dashboard/Logs/Endpoint: je Gruppe count/budget/remaining/over."""
    state = _load_state()
    budgets = _budgets()
    counts = state.get("counts", {})
    groups = set(counts) | set(budgets)
    out = {}
    for grp in sorted(groups):
        cnt = int(counts.get(grp, 0))
        lim = budgets.get(grp)
        try:
            lim = int(lim) if lim is not None else None
        except (TypeError, ValueError):
            lim = None
        out[grp] = {
            "count": cnt,
            "budget": lim,
            "remaining": (max(0, lim - cnt) if lim and lim > 0 else None),
            "over": bool(lim and lim > 0 and cnt >= lim),
        }
    return {"date": state.get("date"), "groups": out}
