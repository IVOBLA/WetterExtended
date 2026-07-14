# mem_monitor.py
"""
Arbeitsspeicher-Monitoring fuer WetterExtended.

Samples RAM-Auslastung alle 5 Minuten via psutil.
Speichert Zeitreihe in train_data/system/mem_history.jsonl.
Haelt maximal 288 Eintraege (24 h x 12 Samples/h).

B358: Ergaenzt cpu_monitor.py um eine RAM-Zeitreihe, u.a. damit im Admin Panel
sichtbar ist, wie knapp der freie RAM waehrend des woechentlichen
ConvLSTM-Trainings (B356/B357) tatsaechlich wird.

Aufruf durch Scheduler (scheduler.py, Job "mem_monitor", IntervalTrigger 5 min).
Direktaufruf fuer Test: python3 mem_monitor.py
"""

import json
import os
from datetime import datetime, timezone, timedelta

try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    _PSUTIL_AVAILABLE = False

from config import SAVE_PATHS
from debug_utils import debug_log

MEM_HISTORY_MAX_ENTRIES: int = 288


def _mem_history_path() -> str:
    """Gibt absoluten Pfad zur JSONL-Datei zurueck; erstellt Verzeichnis falls noetig."""
    sys_dir = SAVE_PATHS.get("system", "train_data/system/")
    os.makedirs(sys_dir.rstrip("/"), exist_ok=True)
    return os.path.join(sys_dir.rstrip("/"), "mem_history.jsonl")


def sample_mem() -> dict | None:
    """
    Liest RAM-Auslastung via psutil.virtual_memory().

    Rueckgabe:
        {"ts_utc": "2026-07-14T13:00:00Z", "total_gb": 15.6, "available_gb": 9.2, "used_pct": 41.0}
        oder None bei Fehler / psutil nicht verfuegbar.
    """
    if not _PSUTIL_AVAILABLE:
        debug_log("[MEM-MONITOR] psutil nicht verfuegbar — kein Sample")
        return None
    try:
        vm = psutil.virtual_memory()
        return {
            "ts_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "total_gb": round(vm.total / (1024 ** 3), 2),
            "available_gb": round(vm.available / (1024 ** 3), 2),
            "used_pct": round(vm.percent, 1),
        }
    except Exception as exc:
        debug_log(f"[MEM-MONITOR] sample_mem Fehler: {exc}")
        return None


def append_mem_sample() -> None:
    """
    Fuehrt sample_mem() aus, haengt Ergebnis an JSONL an und trimmt auf
    MEM_HISTORY_MAX_ENTRIES. Schreibt atomar via .tmp-Datei.
    """
    sample = sample_mem()
    if sample is None:
        return

    path = _mem_history_path()
    entries: list = []

    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except Exception:
                            continue
        except Exception as exc:
            debug_log(f"[MEM-MONITOR] Lesefehler {path}: {exc}")

    entries.append(sample)
    entries = entries[-MEM_HISTORY_MAX_ENTRIES:]

    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
        debug_log(
            f"[MEM-MONITOR] Sample gespeichert: verfuegbar={sample['available_gb']} GB "
            f"belegt={sample['used_pct']}% eintraege={len(entries)}"
        )
    except Exception as exc:
        debug_log(f"[MEM-MONITOR] Schreibfehler {path}: {exc}")
        try:
            os.remove(tmp)
        except Exception:
            pass


def get_mem_history(hours: int = 24) -> list:
    """
    Gibt RAM-History der letzten `hours` Stunden zurueck.

    Jeder Eintrag:
        {"ts_utc": str, "total_gb": float, "available_gb": float, "used_pct": float}

    Leere Liste wenn keine Daten vorhanden oder Datei nicht lesbar.
    """
    path = _mem_history_path()
    if not os.path.exists(path):
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    result: list = []

    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    ts_str = rec.get("ts_utc", "").replace("Z", "")
                    if not ts_str:
                        continue
                    ts = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
                    if ts >= cutoff:
                        result.append(rec)
                except Exception:
                    continue
    except Exception as exc:
        debug_log(f"[MEM-MONITOR] get_mem_history Lesefehler: {exc}")

    return result


if __name__ == "__main__":
    print("Starte RAM-Sample...")
    append_mem_sample()
    history = get_mem_history(hours=24)
    print(f"Gespeicherte Samples (24h): {len(history)}")
    if history:
        last = history[-1]
        print(f"Letzter Eintrag: ts={last['ts_utc']} verfuegbar={last['available_gb']} GB belegt={last['used_pct']}%")
