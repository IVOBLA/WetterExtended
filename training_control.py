"""Gemeinsame Trainingssteuerung für Scheduler und manuelle API-Starts."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from config import SAVE_PATHS
try:
    from debug_utils import debug_log
except Exception:
    def debug_log(message):
        print(message)

_LOCK_STALE_SECONDS = int(os.environ.get("WETTEREXTENDED_TRAINING_LOCK_STALE_SECONDS", "86400"))
_THREAD_LOCK = threading.Lock()


def _models_dir() -> Path:
    path = Path(SAVE_PATHS.get("models", "train_data/models"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _lock_path() -> Path:
    return _models_dir() / "training.lock"


def _status_path() -> Path:
    return _models_dir() / "training_status.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default: Any) -> Any:
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    os.replace(tmp, path)


def _process_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False


def _lock_is_stale(lock_info: dict[str, Any] | None, path: Path) -> bool:
    if not path.exists():
        return False
    info = lock_info or {}
    pid = info.get("pid")
    try:
        pid = int(pid) if pid is not None else None
    except Exception:
        pid = None
    if pid and _process_alive(pid):
        return False
    try:
        age = time.time() - path.stat().st_mtime
    except Exception:
        age = _LOCK_STALE_SECONDS + 1
    return (not pid or not _process_alive(pid)) or age > _LOCK_STALE_SECONDS


def _read_lock() -> dict[str, Any] | None:
    return _read_json(_lock_path(), None)


def _clear_stale_lock() -> bool:
    path = _lock_path()
    info = _read_lock()
    if _lock_is_stale(info, path):
        try:
            path.unlink(missing_ok=True)
            debug_log(f"[TRAINING] Stale Lock bereinigt: {info}")
            return True
        except Exception as exc:
            debug_log(f"[TRAINING] Stale Lock konnte nicht bereinigt werden: {exc}")
    return False


@contextmanager
def acquire_training_lock(run_id: str, source: str):
    with _THREAD_LOCK:
        _clear_stale_lock()
        path = _lock_path()
        info = {"run_id": run_id, "source": source, "pid": os.getpid(), "started_at": _utc_now()}
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            yield False, _read_lock()
            return
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False)
    try:
        yield True, info
    finally:
        try:
            current = _read_lock() or {}
            if current.get("run_id") == run_id:
                _lock_path().unlink(missing_ok=True)
        except Exception as exc:
            debug_log(f"[TRAINING] Lock-Freigabe fehlgeschlagen: {exc}")


def get_training_status() -> dict[str, Any]:
    _clear_stale_lock()
    status = _read_json(_status_path(), {}) or {}
    lock = _read_lock()
    running = bool(lock and not _lock_is_stale(lock, _lock_path()))
    if running:
        status.update({"running": True, "run_id": lock.get("run_id"), "started_at": lock.get("started_at")})
    else:
        status["running"] = False
    status.setdefault("run_id", None)
    status.setdefault("started_at", None)
    status.setdefault("finished_at", None)
    status.setdefault("last_status", "idle")
    status.setdefault("last_error", None)
    status.setdefault("progress_message", "Bereit.")
    status.setdefault("latest_training_meta", _latest_training_meta_full())
    return status


def _update_status(**updates: Any) -> dict[str, Any]:
    status = get_training_status()
    status.update(updates)
    _write_json_atomic(_status_path(), status)
    return status


def _latest_training_meta_full() -> dict[str, Any] | None:
    metas = sorted(_models_dir().glob("v_*/training_meta.json"))
    if not metas:
        return None
    return _read_json(metas[-1], None)


def run_configured_training_pipeline(run_id: str, source: str = "manual", progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    def mark(message: str) -> None:
        debug_log(f"[TRAINING] {source} {run_id}: {message}")
        if progress:
            progress(message)

    import runtime_config
    from model_training import retrain_all

    runtime_config.reload_overrides()
    allow_legacy = "allow_legacy" in str(source)
    runtime_config.patch({"ML_ALLOW_LEGACY_SAMPLES": allow_legacy})
    mark(f"Schema-Policy: {'allow_legacy' if allow_legacy else 'compatible_only'}")
    mark("Trainingspipeline gestartet")
    mark("Dataset-Rebuild und LSTM/LightGBM-Training laufen")
    meta = retrain_all()
    mark("LSTM/LightGBM-Training abgeschlossen; Schwere-Training startet")
    try:
        from severity_dataset import build_severity_dataset
        from severity_training import train_severity_models
        ds = build_severity_dataset()
        tr = train_severity_models()
        debug_log(f"[TRAINING] severity_dataset: {ds}")
        debug_log(f"[TRAINING] severity_training: {tr}")
    except Exception as exc:
        debug_log(f"[TRAINING] Schwere-Training Fehler: {exc}")
        raise
    mark("Trainingspipeline abgeschlossen")
    return meta if isinstance(meta, dict) else {"result": meta}


def run_training_with_lock(run_id: str | None = None, source: str = "manual") -> dict[str, Any]:
    run_id = run_id or f"{source}-{uuid.uuid4().hex[:12]}"
    with acquire_training_lock(run_id, source) as (acquired, lock_info):
        if not acquired:
            return {"started": False, "running": True, "run_id": (lock_info or {}).get("run_id"), "message": "Es läuft bereits ein Training."}
        started_at = _utc_now()
        _update_status(running=True, run_id=run_id, started_at=started_at, finished_at=None, last_status="running", last_error=None, progress_message="Training läuft im Hintergrund", latest_training_meta=_latest_training_meta_full())
        try:
            meta = run_configured_training_pipeline(run_id, source, progress=lambda m: _update_status(progress_message=m, last_status="running"))
            _update_status(running=False, run_id=run_id, started_at=started_at, finished_at=_utc_now(), last_status="success", last_error=None, progress_message="Training erfolgreich abgeschlossen", latest_training_meta=meta)
            return {"started": True, "run_id": run_id, "message": "Training wurde abgeschlossen.", "meta": meta}
        except Exception as exc:
            debug_log(f"[TRAINING] Trainingslauf {run_id} fehlgeschlagen: {exc}")
            _update_status(running=False, run_id=run_id, started_at=started_at, finished_at=_utc_now(), last_status="failed", last_error=str(exc), progress_message="Training fehlgeschlagen", latest_training_meta=_latest_training_meta_full())
            raise


def start_training_background(source: str = "manual") -> tuple[bool, dict[str, Any]]:
    _clear_stale_lock()
    status = get_training_status()
    if status.get("running"):
        return False, {"started": False, "running": True, "run_id": status.get("run_id"), "message": "Es läuft bereits ein Training."}
    run_id = f"{source}-{uuid.uuid4().hex[:12]}"

    def _target() -> None:
        try:
            run_training_with_lock(run_id=run_id, source=source)
        except Exception:
            pass

    thread = threading.Thread(target=_target, name=f"training-{run_id}", daemon=True)
    thread.start()
    return True, {"started": True, "run_id": run_id, "message": "Training wurde gestartet."}
