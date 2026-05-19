"""
Täglicher Daten-Rotations-Job für WetterExtended.

Löscht Dateien in DATA_CLEANUP_PATHS die älter als DATA_RETENTION_DAYS Tage sind.
Protokolliert jede Runde in train_data/evaluation/cleanup_log.jsonl.

Wird täglich vom Scheduler (cleanup_job) aufgerufen.
Kann auch manuell ausgeführt werden: python3 cleanup_old_data.py
"""
import json
import os
import time
from datetime import datetime, timezone

from config import (DATA_CLEANUP_PATHS, DATA_CLEANUP_RETENTION_OVERRIDE,
                    DATA_RETENTION_DAYS, SAVE_PATHS)
from debug_utils import debug_log

_LOG_FILE = os.path.join(
    SAVE_PATHS.get("evaluation", "train_data/evaluation/").rstrip("/"),
    "cleanup_log.jsonl",
)
# Projektstamm = Verzeichnis dieser Datei
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def cleanup_old_data() -> dict:
    """
    Löscht Dateien in DATA_CLEANUP_PATHS die älter als DATA_RETENTION_DAYS Tage sind.

    Gibt Statistik zurück:
      deleted_count  — Anzahl gelöschter Dateien
      freed_mb       — freigegebener Speicher in MB
      dirs_checked   — Anzahl geprüfter Verzeichnisse
      errors         — Liste aufgetretener Fehler (max. 10)
    """
    deleted_count = 0
    freed_bytes = 0
    errors: list = []
    # Retention-Override: bestimmte Verzeichnisse haben kuerzere Aufbewahrungszeit.
    # Fallback: DATA_RETENTION_DAYS (Standard 90 Tage).
    _override = DATA_CLEANUP_RETENTION_OVERRIDE

    for rel_path in DATA_CLEANUP_PATHS:
        # Per-Verzeichnis Retention bestimmen
        retention_days = _override.get(rel_path, DATA_RETENTION_DAYS)
        cutoff_ts = time.time() - retention_days * 86400

        # Pfad relativ zum Projektstamm aufloesen
        abs_path = os.path.normpath(
            os.path.join(_PROJECT_ROOT, rel_path.lstrip("/"))
        )
        if not os.path.isdir(abs_path):
            debug_log(f"[CLEANUP] Verzeichnis nicht gefunden, uebersprungen: {abs_path}")
            continue

        try:
            for fname in os.listdir(abs_path):
                fpath = os.path.join(abs_path, fname)
                if not os.path.isfile(fpath):
                    continue
                try:
                    if os.path.getmtime(fpath) < cutoff_ts:
                        size = os.path.getsize(fpath)
                        os.remove(fpath)
                        deleted_count += 1
                        freed_bytes += size
                except Exception as exc:
                    errors.append(f"{fpath}: {exc}")
                    debug_log(f"[CLEANUP] Fehler bei {fpath}: {exc}")
        except Exception as exc:
            errors.append(f"{abs_path}: {exc}")
            debug_log(f"[CLEANUP] Fehler beim Lesen von {abs_path}: {exc}")

    result = {
        "ts_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "deleted_count": deleted_count,
        "freed_mb": round(freed_bytes / 1_048_576, 2),
        "retention_days": DATA_RETENTION_DAYS,
        "retention_overrides": _override,
        "dirs_checked": len(DATA_CLEANUP_PATHS),
        "errors": errors[:10],  # max. 10 Fehler protokollieren
    }

    # Cleanup-Log schreiben
    os.makedirs(os.path.dirname(_LOG_FILE), exist_ok=True)
    try:
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
    except Exception as exc:
        debug_log(f"[CLEANUP] Konnte Cleanup-Log nicht schreiben: {exc}")

    debug_log(
        f"[CLEANUP] Abgeschlossen: {deleted_count} Dateien gelöscht, "
        f"{result['freed_mb']} MB freigegeben."
    )
    return result


if __name__ == "__main__":
    import pprint

    pprint.pprint(cleanup_old_data())
