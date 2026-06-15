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
from datetime import datetime, timedelta, timezone

from config import (DATA_CLEANUP_PATHS, DATA_CLEANUP_RETENTION_OVERRIDE,
                    DATA_RETENTION_DAYS, SAVE_PATHS)
from debug_utils import debug_log

_LOG_FILE = os.path.join(
    SAVE_PATHS.get("evaluation", "train_data/evaluation/").rstrip("/"),
    "cleanup_log.jsonl",
)
# Projektstamm = Verzeichnis dieser Datei
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def _free_gb() -> float:
    """Freier Speicher auf der Partition von SAVE_PATHS in GB."""
    try:
        import shutil
        path = list(SAVE_PATHS.values())[0] if SAVE_PATHS else "."
        stat = shutil.disk_usage(path)
        return stat.free / (1024 ** 3)
    except Exception:
        return 999.0  # Im Fehlerfall: annehmen dass genug Platz vorhanden


def _prune_eval_jsonl_by_age(filename: str, max_age_hours: int) -> int:
    """B143: Begrenzt eine append-only JSONL in train_data/evaluation/ auf die letzten
    max_age_hours. Zeilen mit ts/ts_utc älter als der Cutoff werden verworfen; nicht
    parsebare Zeilen werden IMMER behalten (nie Daten verlieren). Gibt die Anzahl
    entfernter Zeilen zurück. Nie blockierend."""
    if max_age_hours <= 0:
        return 0
    eval_dir = SAVE_PATHS.get("evaluation", "train_data/evaluation/").rstrip("/")
    path = os.path.join(eval_dir, filename)
    if not os.path.isfile(path):
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    kept: list = []
    removed = 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                drop = False
                try:
                    rec = json.loads(line)
                    raw = rec.get("ts") or rec.get("ts_utc") or ""
                    ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    drop = ts < cutoff
                except Exception:
                    drop = False  # nicht parsebar → behalten
                if drop:
                    removed += 1
                else:
                    kept.append(line if line.endswith("\n") else line + "\n")
        if removed:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.writelines(kept)
            os.replace(tmp, path)
    except Exception as exc:
        debug_log(f"[CLEANUP] eval-JSONL Prune Fehler ({filename}): {exc}")
    return removed


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

    try:
        from config import MIN_FREE_GB_BEFORE_CLEANUP as _MIN_FREE
    except ImportError:
        _MIN_FREE = 5.0

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
                    mtime_ts = os.path.getmtime(fpath)
                    mtime = datetime.fromtimestamp(mtime_ts)
                    file_age_days = (datetime.now() - mtime).days
                    # Bedingung: Datei loeschen wenn Speicher knapp ODER Datei zu alt
                    free_now = _free_gb()
                    too_old = mtime_ts < cutoff_ts
                    low_space = _MIN_FREE > 0 and free_now < _MIN_FREE
                    if not too_old and not low_space:
                        continue  # Platz vorhanden + Datei jung genug -> behalten
                    size = os.path.getsize(fpath)
                    os.remove(fpath)
                    deleted_count += 1
                    freed_bytes += size
                    if too_old:
                        debug_log(f"[CLEANUP] {fname} geloescht (zu_alt, Alter: {file_age_days}d)")
                    elif low_space:
                        debug_log(
                            f"[CLEANUP] {fname} geloescht (Speicher: {free_now:.1f} GB frei < "
                            f"{_MIN_FREE} GB Limit, Alter: {file_age_days}d)"
                        )
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

    # B143: append-only evaluation-JSONLs auf die letzten EVAL_LOG_RETENTION_HOURS begrenzen
    # (stoppt unbegrenztes Wachstum, behält aber > 24h fürs Export-Fenster).
    try:
        from config import EVAL_LOG_RETENTION_HOURS as _eval_hours
    except Exception:
        _eval_hours = 48
    _eval_pruned = 0
    for _fn in ("api_call_counts.jsonl", "api_health.jsonl"):
        _eval_pruned += _prune_eval_jsonl_by_age(_fn, _eval_hours)
    result["eval_lines_pruned"] = _eval_pruned
    if _eval_pruned:
        debug_log(f"[CLEANUP] eval-JSONL Alters-Rotation: {_eval_pruned} Zeilen entfernt (>{_eval_hours}h)")

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
