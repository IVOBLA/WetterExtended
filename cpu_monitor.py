# cpu_monitor.py
"""
CPU-Auslastungs-Monitoring fuer WetterExtended.

Samples CPU-Auslastung aller Kerne alle 5 Minuten via psutil.
Speichert Zeitreihe in train_data/system/cpu_history.jsonl.
Haelt maximal 288 Eintraege (24 h × 12 Samples/h).

Aufruf durch Scheduler (scheduler.py, Job "cpu_monitor", IntervalTrigger 5 min).
Direktaufruf fuer Test: python3 cpu_monitor.py
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

# Maximale Anzahl Eintraege in der JSONL-Datei (24 h bei 5-Minuten-Takt)
CPU_HISTORY_MAX_ENTRIES: int = 288


def _cpu_history_path() -> str:
    """Gibt absoluten Pfad zur JSONL-Datei zurueck; erstellt Verzeichnis falls noetig."""
    sys_dir = SAVE_PATHS.get("system", "train_data/system/")
    os.makedirs(sys_dir.rstrip("/"), exist_ok=True)
    return os.path.join(sys_dir.rstrip("/"), "cpu_history.jsonl")


def sample_cpu() -> dict | None:
    """
    Liest CPU-Auslastung aller Kerne (interval=1 s fuer genaue Messung).

    Rueckgabe:
        {"ts_utc": "2026-05-28T13:00:00Z", "cores": [12.5, 8.2, 45.1, 6.0], "avg": 17.95}
        oder None bei Fehler / psutil nicht verfuegbar.
    """
    if not _PSUTIL_AVAILABLE:
        debug_log("[CPU-MONITOR] psutil nicht verfuegbar — kein Sample")
        return None
    try:
        per_core = psutil.cpu_percent(interval=1, percpu=True)
        if not per_core:
            debug_log("[CPU-MONITOR] cpu_percent lieferte leere Liste")
            return None
        avg = round(sum(per_core) / len(per_core), 1)
        return {
            "ts_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "cores": [round(c, 1) for c in per_core],
            "avg": avg,
        }
    except Exception as exc:
        debug_log(f"[CPU-MONITOR] sample_cpu Fehler: {exc}")
        return None


def append_cpu_sample() -> None:
    """
    Fuehrt sample_cpu() aus, haengt Ergebnis an JSONL an und trimmt auf
    CPU_HISTORY_MAX_ENTRIES. Schreibt atomar via .tmp-Datei.
    """
    sample = sample_cpu()
    if sample is None:
        return

    path = _cpu_history_path()
    entries: list = []

    # Bestehende Eintraege lesen
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
            debug_log(f"[CPU-MONITOR] Lesefehler {path}: {exc}")

    # Neues Sample anhaengen, auf MAX trimmen
    entries.append(sample)
    entries = entries[-CPU_HISTORY_MAX_ENTRIES:]

    # Atomar zurueckschreiben
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
        debug_log(
            f"[CPU-MONITOR] Sample gespeichert: avg={sample['avg']}% "
            f"cores={sample['cores']} eintraege={len(entries)}"
        )
    except Exception as exc:
        debug_log(f"[CPU-MONITOR] Schreibfehler {path}: {exc}")
        try:
            os.remove(tmp)
        except Exception:
            pass


def get_cpu_history(hours: int = 24) -> list:
    """
    Gibt CPU-History der letzten `hours` Stunden zurueck.

    Jeder Eintrag:
        {"ts_utc": str, "cores": [float, ...], "avg": float}

    Leere Liste wenn keine Daten vorhanden oder Datei nicht lesbar.
    """
    path = _cpu_history_path()
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
        debug_log(f"[CPU-MONITOR] get_cpu_history Lesefehler: {exc}")

    return result


if __name__ == "__main__":
    print("Starte CPU-Sample...")
    append_cpu_sample()
    history = get_cpu_history(hours=24)
    print(f"Gespeicherte Samples (24h): {len(history)}")
    if history:
        last = history[-1]
        print(f"Letzter Eintrag: ts={last['ts_utc']} avg={last['avg']}% cores={last['cores']}")
