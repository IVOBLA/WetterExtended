"""Sichere Backup- und Reset-Funktionen fuer ML-Trainingsartefakte."""
from __future__ import annotations

import json
import multiprocessing
import os
import shutil
import stat
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from config import SAVE_PATHS

PROJECT_ROOT = Path(__file__).resolve().parent
TRAIN_DATA_DIR = (PROJECT_ROOT / "train_data").resolve()
BACKUP_DIR = PROJECT_ROOT / "backups"
ARCHIVE_DIR = TRAIN_DATA_DIR / "archived_training_sources"
STATUS_FILE = TRAIN_DATA_DIR / "ml_reset_status.json"
BACKUP_STATUS_FILE = TRAIN_DATA_DIR / "ml_backup_status.json"
ML_JOB_LOCK_FILE = TRAIN_DATA_DIR / "ml_job.lock"
MANIFEST_NAME = "manifest.json"

RESET_MODES = {"models_only", "full_new_data_only"}
EXPECTED_MAIN_DIRS = ["models", "dataset", "objects", "weather", "hydro", "statistics"]
MODEL_ARTIFACT_PATTERNS = ["*.keras", "*.h5", "*.joblib", "*.txt", "training_meta.json", "*_metrics.json"]
DATASET_ARTIFACT_PATTERNS = ["*.npz", "*.parquet", "*.csv", "*.pkl", "*.joblib", "*.json"]
TRAINING_SOURCE_KEYS = ("objects", "weather")
NEVER_DELETE_REL = {
    ".env",
    "runtime_overrides.json",
    "train_data/runtime_overrides.json",
    "train_data/hydro",
    "train_data/statistics",
    "train_data/cell_filters",
    "train_data/dem",
    "backups",
}
RESET_STEPS = ["preflight", "backup", "remove_models", "remove_dataset", "archive_training_sources", "write_status", "finished"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _rel(path: Path) -> str:
    return path.resolve().relative_to(PROJECT_ROOT).as_posix()


def _rel_lexical(path: Path) -> str:
    absolute = path.absolute()
    try:
        return absolute.relative_to(PROJECT_ROOT.resolve(strict=False)).as_posix()
    except ValueError:
        return str(absolute)


def _ensure_inside(path: Path, root: Path | None = None) -> Path:
    if root is None:
        root = TRAIN_DATA_DIR
    root_resolved = root.resolve(strict=False)
    if path.is_symlink():
        lexical = path.absolute().parent.resolve(strict=False) / path.name
        if lexical != root_resolved and root_resolved not in lexical.parents:
            raise ValueError(f"Pfad ausserhalb des erlaubten Bereichs: {path}")
        return lexical
    resolved = path.resolve(strict=False)
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise ValueError(f"Pfad ausserhalb des erlaubten Bereichs: {path}")
    return resolved


def _safe_rmtree(path: Path) -> None:
    resolved = _ensure_inside(path)
    if not resolved.exists() and not resolved.is_symlink():
        return
    if resolved.is_symlink() or resolved.is_file():
        resolved.unlink()
        return
    for child in resolved.iterdir():
        if child.is_symlink():
            child.unlink()
        elif child.is_dir():
            _safe_rmtree(child)
        else:
            child.unlink()
    resolved.rmdir()


def _safe_unlink(path: Path, root: Path | None = None) -> None:
    resolved = _ensure_inside(path, root)
    if resolved.exists() or resolved.is_symlink():
        if resolved.is_dir() and not resolved.is_symlink():
            _safe_rmtree(resolved)
        else:
            resolved.unlink()


def _project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        return {}


def _pid_running(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False


def _lock_owner() -> dict:
    data = _read_json(ML_JOB_LOCK_FILE)
    if data and not _pid_running(data.get("pid")):
        try:
            ML_JOB_LOCK_FILE.unlink()
        except FileNotFoundError:
            pass
        return {}
    return data


def _acquire_ml_job_lock(kind: str, job_id: str | None = None) -> dict:
    TRAIN_DATA_DIR.mkdir(parents=True, exist_ok=True)
    owner = {
        "kind": kind,
        "job_id": job_id,
        "pid": os.getpid(),
        "started_at": _utc_now().isoformat(),
    }
    try:
        fd = os.open(str(ML_JOB_LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(owner, fh, indent=2, ensure_ascii=False)
        return owner
    except FileExistsError:
        current = _lock_owner()
        if current:
            raise RuntimeError(f"ML-Job läuft bereits: {current.get('kind', 'unknown')}")
        return _acquire_ml_job_lock(kind, job_id)


def _release_ml_job_lock(owner: dict | None = None) -> None:
    current = _read_json(ML_JOB_LOCK_FILE)
    if owner and current and current.get("job_id") != owner.get("job_id"):
        return
    try:
        ML_JOB_LOCK_FILE.unlink()
    except FileNotFoundError:
        pass


def _update_existing_ml_job_lock(job_id: str, **updates) -> dict:
    owner = _read_json(ML_JOB_LOCK_FILE)
    if not owner or owner.get("job_id") != job_id:
        return owner
    owner.update(updates)
    _write_json(ML_JOB_LOCK_FILE, owner)
    return owner



def _section_counts(path: Path, root: Path | None = None, max_examples: int = 8) -> dict:
    root = root or PROJECT_ROOT
    path = _ensure_inside(path, root)
    files = dirs = bytes_total = 0
    examples: list[str] = []
    if not path.exists() and not path.is_symlink():
        return {"files": 0, "dirs": 0, "bytes": 0, "size_mb": 0.0, "examples": []}
    if path.is_symlink():
        files = 1
        examples.append(_rel_lexical(path))
        return {"files": files, "dirs": dirs, "bytes": 0, "size_mb": 0.0, "examples": examples}
    if path.is_file():
        files = 1
        try:
            bytes_total = path.stat().st_size
        except OSError:
            bytes_total = 0
        examples.append(_rel(path))
        return {"files": files, "dirs": dirs, "bytes": bytes_total, "size_mb": round(bytes_total / 1024 / 1024, 2), "examples": examples}
    def walk(directory: Path) -> None:
        nonlocal files, dirs, bytes_total
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    child = Path(entry.path)
                    _ensure_inside(child, root)
                    rel = _rel_lexical(child)
                    if len(examples) < max_examples:
                        examples.append(rel)
                    try:
                        if entry.is_symlink():
                            files += 1
                        elif entry.is_dir(follow_symlinks=False):
                            dirs += 1
                            walk(child)
                        elif entry.is_file(follow_symlinks=False):
                            files += 1
                            bytes_total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            return
    walk(path)
    return {"files": files, "dirs": dirs, "bytes": bytes_total, "size_mb": round(bytes_total / 1024 / 1024, 2), "examples": examples}


def _section(area: str, path: Path, action: str, root: Path | None = None) -> dict:
    safe_root = root or (PROJECT_ROOT if area in {"project", "backups"} else TRAIN_DATA_DIR)
    path = _ensure_inside(path, safe_root)
    counts = _section_counts(path, safe_root)
    return {"area": area, "path": _rel(path), "action": action, **counts}


def build_reset_plan(mode: str) -> dict:
    if mode not in RESET_MODES:
        raise ValueError(f"Ungueltiger Reset-Modus: {mode}")
    models = _project_path(SAVE_PATHS.get("models", "train_data/models"))
    dataset = _project_path(SAVE_PATHS.get("dataset", "train_data/dataset"))
    objects = _project_path(SAVE_PATHS.get("objects", "train_data/objects"))
    weather = _project_path(SAVE_PATHS.get("weather", "train_data/weather"))
    delete_sections = [_section("models", models, "delete_recreate"), _section("dataset", dataset, "delete_children")]
    archive_sections = []
    if mode == "full_new_data_only":
        archive_sections = [_section("objects", objects, "archive_recreate"), _section("weather", weather, "archive_recreate")]
    preserved_specs = [
        ("hydro", TRAIN_DATA_DIR / "hydro", TRAIN_DATA_DIR),
        ("statistics", TRAIN_DATA_DIR / "statistics", TRAIN_DATA_DIR),
        ("cell_filters", TRAIN_DATA_DIR / "cell_filters", TRAIN_DATA_DIR),
        ("dem", TRAIN_DATA_DIR / "dem", TRAIN_DATA_DIR),
        ("env", PROJECT_ROOT / ".env", PROJECT_ROOT),
        ("runtime_config", PROJECT_ROOT / "runtime_overrides.json", PROJECT_ROOT),
        ("train_runtime_config", TRAIN_DATA_DIR / "runtime_overrides.json", TRAIN_DATA_DIR),
        ("backups", BACKUP_DIR, PROJECT_ROOT),
        ("archived_training_sources", ARCHIVE_DIR, TRAIN_DATA_DIR),
    ]
    preserved_sections = [_section(area, path, "preserve", root) for area, path, root in preserved_specs]
    return {"mode": mode, "will_backup": True, "delete_sections": delete_sections, "archive_sections": archive_sections, "preserved_sections": preserved_sections}


def _sum_sections(sections: list[dict]) -> dict:
    files = sum(int(s.get("files") or 0) for s in sections)
    dirs = sum(int(s.get("dirs") or 0) for s in sections)
    bytes_total = sum(int(s.get("bytes") or 0) for s in sections)
    return {"files": files, "dirs": dirs, "bytes": bytes_total, "size_mb": round(bytes_total / 1024 / 1024, 2), "sections": sections}


def _reset_status_payload(**updates) -> dict:
    payload = _read_json(STATUS_FILE)
    payload.update(updates)
    _write_json(STATUS_FILE, payload)
    return payload


def _mark_reset_step(step: str, job_id: str, **updates) -> dict:
    idx = RESET_STEPS.index(step) if step in RESET_STEPS else 0
    percent = int(idx / (len(RESET_STEPS) - 1) * 100)
    return _reset_status_payload(status="running", running=True, finished=False, failed=False, job_id=job_id, current_step=step, progress=step, percent=percent, **updates)

def _backup_status_payload(**updates) -> dict:
    payload = _read_json(BACKUP_STATUS_FILE)
    payload.update(updates)
    _write_json(BACKUP_STATUS_FILE, payload)
    return payload


def _legacy_backup_dir() -> Path:
    return TRAIN_DATA_DIR / "backups"


def _migrate_legacy_backups() -> list[str]:
    warnings = []
    legacy = _legacy_backup_dir()
    if not legacy.exists() or legacy == BACKUP_DIR:
        return warnings
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    for old_zip in legacy.glob("*_train_data.zip"):
        target = BACKUP_DIR / old_zip.name
        if target.exists():
            continue
        try:
            shutil.move(str(old_zip), str(target))
        except Exception as exc:
            warnings.append(f"Legacy-Backup konnte nicht migriert werden: {old_zip.name}: {exc}")
    return warnings


def _is_excluded_from_backup(path: Path, zip_path: Path) -> bool:
    rel = path.relative_to(TRAIN_DATA_DIR)
    parts = rel.parts
    if parts and parts[0] == "backups":
        return True
    if path == zip_path or path == zip_path.with_suffix(".zip.tmp"):
        return True
    if path.name.endswith(".tmp"):
        return True
    if path.name.endswith("_train_data.zip"):
        return True
    return False


def _iter_train_data_entries(zip_path: Path, warnings: list[str]) -> Iterable[Path]:
    def walk(directory: Path) -> Iterable[Path]:
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    if _is_excluded_from_backup(path, zip_path):
                        continue
                    yield path
                    try:
                        is_link = entry.is_symlink()
                    except OSError as exc:
                        warnings.append(f"Symlink-/Dateiprüfung fehlgeschlagen: {path}: {exc}")
                        continue
                    if is_link:
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            yield from walk(path)
                    except OSError as exc:
                        warnings.append(f"Verzeichnis übersprungen: {path}: {exc}")
        except OSError as exc:
            warnings.append(f"Verzeichnis konnte nicht gelesen werden: {directory}: {exc}")

    yield from walk(TRAIN_DATA_DIR)


def _write_zip_symlink(zf: zipfile.ZipFile, path: Path, arcname: str) -> None:
    """Store a symlink entry in a ZIP without following its target."""
    info = zipfile.ZipInfo(arcname)
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    zf.writestr(info, os.readlink(path))


def _check_symlink_warning(path: Path, warnings: list[str]) -> None:
    try:
        path.stat()
    except OSError as exc:
        warnings.append(f"Problematischer Symlink übersprungen/gekennzeichnet: {path}: {exc}")


def create_backup(reset_type: str = "manual") -> dict:
    TRAIN_DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    migration_warnings = _migrate_legacy_backups()
    ts = _utc_now().strftime("%Y%m%d_%H%M%S")
    zip_path = BACKUP_DIR / f"{ts}_train_data.zip"
    warnings = list(migration_warnings)
    skipped_entries = []
    symlink_warnings = []
    manifest = {
        "created": _utc_now().isoformat(),
        "reset_type": reset_type,
        "project_root": str(PROJECT_ROOT),
        "source": "train_data",
        "expected_main_dirs": EXPECTED_MAIN_DIRS,
        "warnings": warnings,
        "skipped_entries": skipped_entries,
        "symlink_warnings": symlink_warnings,
    }
    tmp_path = zip_path.with_suffix(".zip.tmp")
    with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in _iter_train_data_entries(zip_path, warnings):
            arc = Path("train_data") / path.relative_to(TRAIN_DATA_DIR)
            try:
                if path.is_symlink():
                    before = len(symlink_warnings)
                    _check_symlink_warning(path, symlink_warnings)
                    if len(symlink_warnings) > before:
                        skipped_entries.append(arc.as_posix())
                    _write_zip_symlink(zf, path, arc.as_posix())
                elif path.is_dir():
                    zf.writestr(arc.as_posix().rstrip("/") + "/", b"")
                elif path.is_file():
                    zf.write(path, arc.as_posix())
            except OSError as exc:
                skipped_entries.append(arc.as_posix())
                warnings.append(f"Eintrag übersprungen: {arc.as_posix()}: {exc}")
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2, ensure_ascii=False))
    os.replace(tmp_path, zip_path)
    info = validate_backup(zip_path)
    if not info["valid"]:
        raise RuntimeError("Backup-Validierung fehlgeschlagen: " + "; ".join(info["errors"]))
    return backup_info(zip_path) | {"valid": True, "manifest": manifest}


def _run_backup_job(job_id: str, reset_type: str = "manual") -> None:
    owner = _update_existing_ml_job_lock(job_id, pid=os.getpid()) or {"kind": "backup", "job_id": job_id}
    try:
        try:
            from debug_utils import debug_log
            debug_log(f"[ML_BACKUP] Hintergrundjob gestartet: {job_id}")
        except Exception:
            pass
        _backup_status_payload(
            status="running",
            running=True,
            finished=False,
            failed=False,
            pid=os.getpid(),
            job_id=job_id,
            backup_id=None,
            filename=None,
            started_at=_utc_now().isoformat(),
            finished_at=None,
            error=None,
            progress="Backup wird erstellt...",
        )
        backup = create_backup(reset_type)
        try:
            from debug_utils import debug_log
            debug_log(f"[ML_BACKUP] Hintergrundjob abgeschlossen: {job_id} -> {backup.get('id')}")
        except Exception:
            pass
        _backup_status_payload(
            status="finished",
            running=False,
            finished=True,
            failed=False,
            pid=os.getpid(),
            job_id=job_id,
            backup_id=backup.get("id"),
            filename=backup.get("id"),
            finished_at=_utc_now().isoformat(),
            error=None,
            progress="Backup abgeschlossen.",
            backup=backup,
        )
    except Exception as exc:
        try:
            from debug_utils import debug_log
            debug_log(f"[ML_BACKUP] Hintergrundjob fehlgeschlagen: {job_id}: {exc}")
        except Exception:
            pass
        _backup_status_payload(
            status="failed",
            running=False,
            finished=False,
            failed=True,
            pid=os.getpid(),
            job_id=job_id,
            finished_at=_utc_now().isoformat(),
            error=str(exc),
            progress="Backup fehlgeschlagen.",
        )
    finally:
        _release_ml_job_lock(owner)


def start_backup_background(reset_type: str = "manual") -> dict:
    current = _lock_owner()
    if current:
        raise RuntimeError(f"ML-Job läuft bereits: {current.get('kind', 'unknown')}")
    job_id = f"backup_{_utc_now().strftime('%Y%m%d_%H%M%S_%f')}"
    owner = _acquire_ml_job_lock("backup", job_id)
    _backup_status_payload(
        status="starting",
        running=True,
        finished=False,
        failed=False,
        pid=None,
        job_id=job_id,
        backup_id=None,
        filename=None,
        started_at=_utc_now().isoformat(),
        finished_at=None,
        error=None,
        progress="Backup wird gestartet...",
    )
    try:
        ctx = multiprocessing.get_context("fork") if hasattr(os, "fork") else multiprocessing
        process = ctx.Process(target=_run_backup_job, args=(job_id, reset_type), daemon=False)
        process.start()
        if (_read_json(ML_JOB_LOCK_FILE) or {}).get("job_id") == job_id:
            _backup_status_payload(status="running", pid=process.pid, progress="Backup wird erstellt...")
    except Exception:
        _release_ml_job_lock(owner)
        raise
    return {"started": True, "job_id": job_id, "status": "running"}


def backup_job_status() -> dict:
    status = _read_json(BACKUP_STATUS_FILE)
    owner = _lock_owner()
    if status.get("status") in {"running", "starting"} and not owner and not _pid_running(status.get("pid")):
        status = _backup_status_payload(
            status="failed",
            running=False,
            finished=False,
            failed=True,
            finished_at=_utc_now().isoformat(),
            error=status.get("error") or "Backup-Prozess ist nicht mehr aktiv.",
            progress="Backup fehlgeschlagen.",
        )
    return {
        "running": bool(status.get("running")),
        "finished": bool(status.get("finished")),
        "failed": bool(status.get("failed")),
        "progress": status.get("progress") or ("Backup wird erstellt..." if status.get("running") else ""),
        "status": status.get("status") or "idle",
        "pid": status.get("pid"),
        "job_id": status.get("job_id"),
        "started_at": status.get("started_at"),
        "finished_at": status.get("finished_at"),
        "error": status.get("error"),
        "backup": status.get("backup"),
        "backup_id": status.get("backup_id"),
        "filename": status.get("filename"),
    }


def validate_backup(path: Path) -> dict:
    errors = []
    if not path.exists():
        errors.append("Datei existiert nicht")
    elif path.stat().st_size <= 0:
        errors.append("Datei ist leer")
    names = []
    if not errors:
        try:
            with zipfile.ZipFile(path, "r") as zf:
                bad = zf.testzip()
                if bad:
                    errors.append(f"Defekter ZIP-Eintrag: {bad}")
                names = zf.namelist()
                if MANIFEST_NAME not in names:
                    errors.append("Manifest fehlt")
                for dirname in EXPECTED_MAIN_DIRS:
                    source = TRAIN_DATA_DIR / dirname
                    if source.exists() and not any(n.startswith(f"train_data/{dirname}/") for n in names):
                        errors.append(f"Hauptverzeichnis fehlt: {dirname}")
        except zipfile.BadZipFile:
            errors.append("ZIP nicht lesbar")
    return {"valid": not errors, "errors": errors, "entries": len(names)}


def backup_info(path: Path) -> dict:
    stat = path.stat()
    reset_type = "unknown"
    created = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
    try:
        with zipfile.ZipFile(path, "r") as zf:
            manifest = json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
            reset_type = manifest.get("reset_type", reset_type)
            created = manifest.get("created", created)
    except Exception:
        pass
    return {"id": path.name, "path": _rel(path), "created": created, "size_bytes": stat.st_size, "size_mb": round(stat.st_size / 1024 / 1024, 2), "reset_type": reset_type}


def list_backups() -> list[dict]:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_backups()
    return [backup_info(p) for p in sorted(BACKUP_DIR.glob("*_train_data.zip"), reverse=True)]


def get_backup_path(backup_id: str) -> Path:
    if "/" in backup_id or "\\" in backup_id or not backup_id.endswith(".zip"):
        raise ValueError("Ungueltige Backup-ID")
    return _ensure_inside(BACKUP_DIR / backup_id, BACKUP_DIR)


def delete_backup(backup_id: str) -> None:
    _safe_unlink(get_backup_path(backup_id), BACKUP_DIR)


def _remove_models() -> dict:
    models = _ensure_inside(_project_path(SAVE_PATHS.get("models", "train_data/models")))
    section = _section("models", models, "delete_recreate")
    if models.exists() or models.is_symlink():
        _safe_unlink(models)
    models.mkdir(parents=True, exist_ok=True)
    return section


def _remove_dataset() -> dict:
    ds = _ensure_inside(_project_path(SAVE_PATHS.get("dataset", "train_data/dataset")))
    section = _section("dataset", ds, "delete_children")
    if ds.exists() and not ds.is_symlink():
        for item in list(ds.iterdir()):
            _safe_unlink(item)
    elif ds.exists() or ds.is_symlink():
        _safe_unlink(ds)
    ds.mkdir(parents=True, exist_ok=True)
    return section


def _archive_training_sources() -> list[dict]:
    ts = _utc_now().strftime("%Y%m%d_%H%M%S")
    target_root = _ensure_inside(ARCHIVE_DIR / ts)
    archived = []
    for key in TRAINING_SOURCE_KEYS:
        src = _ensure_inside(_project_path(SAVE_PATHS.get(key, f"train_data/{key}")))
        section = _section(key, src, "archive_recreate")
        if not src.exists() and not src.is_symlink():
            src.mkdir(parents=True, exist_ok=True)
            continue
        dst = _ensure_inside(target_root / key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        src.mkdir(parents=True, exist_ok=True)
        archived.append(section | {"source": _rel(src), "archive": _rel(dst)})
    return archived


def ml_status() -> dict:
    models_dir = _project_path(SAVE_PATHS.get("models", "train_data/models"))
    current = models_dir / "current"
    dataset = _project_path(SAVE_PATHS.get("dataset", "train_data/dataset")) / "dataset.npz"
    samples = 0
    if dataset.exists():
        try:
            import numpy as np
            samples = int(np.load(dataset, allow_pickle=True)["X"].shape[0])
        except Exception:
            samples = 0
    versions = [p for p in models_dir.glob("v_*") if p.is_dir()] if models_dir.exists() else []
    reset_status = {}
    if STATUS_FILE.exists():
        try:
            reset_status = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        except Exception:
            reset_status = {}
    backups = list_backups()
    meta_path = current / "training_meta.json"
    latest_training = None
    runtime_status = {}
    try:
        from ml_readiness import get_forecast_runtime_status
        runtime_status = get_forecast_runtime_status(write_json=False, model_dir=str(current))
    except Exception:
        runtime_status = {}
    active_version = runtime_status.get("active_model_version") or runtime_status.get("ml_model_version")
    if meta_path.exists():
        try:
            latest_training = json.loads(meta_path.read_text(encoding="utf-8")).get("created_at")
        except Exception:
            latest_training = None
    return {"active_model_version": active_version, "model_count": len(versions), "models_present": bool(active_version), "dataset_present": dataset.exists(), "samples": samples, "latest_training": latest_training, "runtime_status": runtime_status, "last_reset": reset_status, "last_backup": backups[0] if backups else None, "backups_count": len(backups)}



def _training_running() -> bool:
    try:
        from training_control import get_training_status
        return bool(get_training_status().get("running"))
    except Exception:
        return False


def _run_reset_job(job_id: str, mode: str) -> None:
    owner = _update_existing_ml_job_lock(job_id, pid=os.getpid()) or {"kind": "reset", "job_id": job_id}
    plan = {}
    try:
        plan = build_reset_plan(mode)
        _mark_reset_step("preflight", job_id, pid=os.getpid(), mode=mode, plan=plan)
        _mark_reset_step("backup", job_id)
        backup = create_backup(mode)
        _mark_reset_step("remove_models", job_id, backup=backup)
        removed_models = _remove_models()
        _mark_reset_step("remove_dataset", job_id)
        removed_dataset = _remove_dataset()
        archived = []
        if mode == "full_new_data_only":
            _mark_reset_step("archive_training_sources", job_id)
            archived = _archive_training_sources()
        else:
            _mark_reset_step("archive_training_sources", job_id)
        try:
            from feature_schema import get_current_feature_schema
            _schema = get_current_feature_schema()
        except Exception:
            _schema = {}
        deleted_counts = _sum_sections([removed_models, removed_dataset])
        archived_counts = _sum_sections(archived)
        result = {
            "status": "reset_done", "mode": mode, "backup": backup.get("path"), "backup_id": backup.get("id"),
            "backup_size_mb": backup.get("size_mb"), "created": _utc_now().isoformat(),
            "next_action": "collect_new_data" if mode == "full_new_data_only" else "rebuild_dataset_or_retrain",
            "feature_schema_hash": _schema.get("feature_schema_hash"), "feature_schema_version": _schema.get("schema_version"),
            "schema_status": "reset_to_current_runtime_schema",
            "fallback": "ML-Modell fehlt, kinematischer Fallback aktiv, neue Trainingsdaten werden ab jetzt gesammelt.",
        }
        _mark_reset_step("write_status", job_id, result=result, deleted_counts=deleted_counts, archived_counts=archived_counts)
        _reset_status_payload(status="finished", running=False, finished=True, failed=False, job_id=job_id, pid=os.getpid(), mode=mode, finished_at=_utc_now().isoformat(), current_step="finished", progress="Reset abgeschlossen", percent=100, error=None, plan=plan, backup=backup, result=result, deleted_counts=deleted_counts, archived_counts=archived_counts, preserved_sections=plan.get("preserved_sections", []))
    except Exception as exc:
        _reset_status_payload(status="failed", running=False, finished=False, failed=True, job_id=job_id, pid=os.getpid(), mode=mode, finished_at=_utc_now().isoformat(), current_step="failed", progress="Reset fehlgeschlagen", error=str(exc), plan=plan)
    finally:
        _release_ml_job_lock(owner)


def start_reset_background(mode: str) -> dict:
    if mode not in RESET_MODES:
        raise ValueError(f"Ungueltiger Reset-Modus: {mode}")
    current = _lock_owner()
    if current:
        raise RuntimeError(f"ML-Job läuft bereits: {current.get('kind', 'unknown')}")
    if _training_running():
        raise RuntimeError("Training läuft bereits")
    job_id = f"reset_{_utc_now().strftime('%Y%m%d_%H%M%S_%f')}"
    plan = build_reset_plan(mode)
    owner = _acquire_ml_job_lock("reset", job_id)
    _reset_status_payload(status="starting", running=True, finished=False, failed=False, job_id=job_id, pid=None, mode=mode, started_at=_utc_now().isoformat(), finished_at=None, current_step="preflight", progress="Reset wird gestartet", percent=0, error=None, plan=plan, backup=None, result=None, deleted_counts=None, archived_counts=None, preserved_sections=plan.get("preserved_sections", []))
    try:
        ctx = multiprocessing.get_context("fork") if hasattr(os, "fork") else multiprocessing
        process = ctx.Process(target=_run_reset_job, args=(job_id, mode), daemon=False)
        process.start()
        _update_existing_ml_job_lock(job_id, pid=process.pid)
        _reset_status_payload(status="running", pid=process.pid, progress="Reset läuft", percent=1)
    except Exception:
        _release_ml_job_lock(owner)
        raise
    return {"started": True, "job_id": job_id, "status": "running", "plan": plan}


def reset_job_status() -> dict:
    status = _read_json(STATUS_FILE)
    owner = _lock_owner()
    if status.get("status") in {"running", "starting"} and not owner and not _pid_running(status.get("pid")):
        status = _reset_status_payload(status="failed", running=False, finished=False, failed=True, finished_at=_utc_now().isoformat(), error=status.get("error") or "Reset-Prozess ist nicht mehr aktiv.", progress="Reset fehlgeschlagen", current_step="failed")
    status.setdefault("status", "idle")
    status.setdefault("running", False)
    status.setdefault("finished", False)
    status.setdefault("failed", False)
    status.setdefault("percent", 0)
    return status

def reset_ml(mode: str) -> dict:
    if mode not in RESET_MODES:
        raise ValueError(f"Ungueltiger Reset-Modus: {mode}")
    owner = _acquire_ml_job_lock("reset", f"reset_{_utc_now().strftime('%Y%m%d_%H%M%S_%f')}")
    try:
        backup = create_backup(mode)
        removed_models = _remove_models()
        removed_dataset = _remove_dataset()
        archived = _archive_training_sources() if mode == "full_new_data_only" else []
        try:
            from feature_schema import get_current_feature_schema
            _schema = get_current_feature_schema()
        except Exception:
            _schema = {}
        status = {
            "status": "reset_done",
            "mode": mode,
            "backup": backup["path"],
            "backup_id": backup["id"],
            "backup_size_mb": backup["size_mb"],
            "created": _utc_now().isoformat(),
            "next_action": "collect_new_data" if mode == "full_new_data_only" else "rebuild_dataset_or_retrain",
            "removed_models_entries": removed_models.get("files", 0) + removed_models.get("dirs", 0),
            "removed_dataset_entries": removed_dataset.get("files", 0) + removed_dataset.get("dirs", 0),
            "deleted_counts": _sum_sections([removed_models, removed_dataset]),
            "archived_counts": _sum_sections(archived),
            "archived_training_sources": archived,
            "feature_schema_hash": _schema.get("feature_schema_hash"),
            "feature_schema_version": _schema.get("schema_version"),
            "schema_status": "reset_to_current_runtime_schema",
        }
        _write_json(STATUS_FILE, status)
        return {"ok": True, "backup": backup, "reset": status, "status": ml_status()}
    finally:
        _release_ml_job_lock(owner)
