"""Sichere Backup- und Reset-Funktionen fuer ML-Trainingsartefakte."""
from __future__ import annotations

import json
import os
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from config import SAVE_PATHS

PROJECT_ROOT = Path(__file__).resolve().parent
TRAIN_DATA_DIR = (PROJECT_ROOT / "train_data").resolve()
BACKUP_DIR = TRAIN_DATA_DIR / "backups"
ARCHIVE_DIR = TRAIN_DATA_DIR / "archived_training_sources"
STATUS_FILE = TRAIN_DATA_DIR / "ml_reset_status.json"
MANIFEST_NAME = "manifest.json"

RESET_MODES = {"models_only", "full_new_data_only"}
EXPECTED_MAIN_DIRS = ["models", "dataset", "objects", "weather", "hydro", "statistics"]
MODEL_ARTIFACT_PATTERNS = ["*.keras", "*.h5", "*.joblib", "*.txt", "training_meta.json", "*_metrics.json"]
DATASET_ARTIFACT_PATTERNS = ["*.npz", "*.parquet", "*.csv", "*.pkl", "*.joblib", "*.json"]
TRAINING_SOURCE_KEYS = ("objects", "weather")
NEVER_DELETE_REL = {
    ".env",
    "train_data/runtime_overrides.json",
    "train_data/hydro",
    "train_data/statistics",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _rel(path: Path) -> str:
    return path.resolve().relative_to(PROJECT_ROOT).as_posix()


def _ensure_inside(path: Path, root: Path | None = None) -> Path:
    if root is None:
        root = TRAIN_DATA_DIR
    resolved = path.resolve(strict=False)
    root_resolved = root.resolve(strict=False)
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


def _safe_unlink(path: Path) -> None:
    resolved = _ensure_inside(path)
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


def _iter_train_data_entries(zip_path: Path) -> Iterable[Path]:
    for path in TRAIN_DATA_DIR.rglob("*"):
        if path.resolve(strict=False) == zip_path.resolve(strict=False):
            continue
        if path.name.endswith(".tmp") and path.parent == BACKUP_DIR:
            continue
        yield path


def create_backup(reset_type: str = "manual") -> dict:
    TRAIN_DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = _utc_now().strftime("%Y%m%d_%H%M%S")
    zip_path = BACKUP_DIR / f"{ts}_train_data.zip"
    manifest = {
        "created": _utc_now().isoformat(),
        "reset_type": reset_type,
        "project_root": str(PROJECT_ROOT),
        "source": "train_data",
        "expected_main_dirs": EXPECTED_MAIN_DIRS,
    }
    tmp_path = zip_path.with_suffix(".zip.tmp")
    with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2, ensure_ascii=False))
        for path in _iter_train_data_entries(zip_path):
            arc = Path("train_data") / path.relative_to(TRAIN_DATA_DIR)
            if path.is_dir():
                zf.writestr(arc.as_posix().rstrip("/") + "/", b"")
            elif path.is_file() and not path.is_symlink():
                zf.write(path, arc.as_posix())
    os.replace(tmp_path, zip_path)
    info = validate_backup(zip_path)
    if not info["valid"]:
        raise RuntimeError("Backup-Validierung fehlgeschlagen: " + "; ".join(info["errors"]))
    return backup_info(zip_path) | {"valid": True, "manifest": manifest}


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
    return [backup_info(p) for p in sorted(BACKUP_DIR.glob("*_train_data.zip"), reverse=True)]


def get_backup_path(backup_id: str) -> Path:
    if "/" in backup_id or "\\" in backup_id or not backup_id.endswith(".zip"):
        raise ValueError("Ungueltige Backup-ID")
    return _ensure_inside(BACKUP_DIR / backup_id, BACKUP_DIR)


def delete_backup(backup_id: str) -> None:
    _safe_unlink(get_backup_path(backup_id))


def _remove_models() -> int:
    models = _ensure_inside(_project_path(SAVE_PATHS.get("models", "train_data/models")))
    count = 0
    if models.exists() or models.is_symlink():
        count = sum(1 for _ in models.rglob("*")) if models.is_dir() and not models.is_symlink() else 1
        _safe_unlink(models)
    models.mkdir(parents=True, exist_ok=True)
    return count


def _remove_dataset() -> int:
    ds = _ensure_inside(_project_path(SAVE_PATHS.get("dataset", "train_data/dataset")))
    count = 0
    if ds.exists():
        for item in list(ds.iterdir()):
            count += 1
            _safe_unlink(item)
    ds.mkdir(parents=True, exist_ok=True)
    return count


def _archive_training_sources() -> list[dict]:
    ts = _utc_now().strftime("%Y%m%d_%H%M%S")
    target_root = ARCHIVE_DIR / ts
    archived = []
    for key in TRAINING_SOURCE_KEYS:
        src = _ensure_inside(_project_path(SAVE_PATHS.get(key, f"train_data/{key}")))
        if not src.exists():
            src.mkdir(parents=True, exist_ok=True)
            continue
        dst = _ensure_inside(target_root / key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        src.mkdir(parents=True, exist_ok=True)
        archived.append({"source": _rel(src), "archive": _rel(dst)})
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
    active_version = None
    if current.exists() or current.is_symlink():
        active_version = current.resolve().name if current.resolve().name.startswith("v_") else "current"
    if meta_path.exists():
        try:
            latest_training = json.loads(meta_path.read_text(encoding="utf-8")).get("created_at")
        except Exception:
            latest_training = None
    return {"active_model_version": active_version, "model_count": len(versions), "models_present": bool(active_version), "dataset_present": dataset.exists(), "samples": samples, "latest_training": latest_training, "last_reset": reset_status, "last_backup": backups[0] if backups else None, "backups_count": len(backups)}


def reset_ml(mode: str) -> dict:
    if mode not in RESET_MODES:
        raise ValueError(f"Ungueltiger Reset-Modus: {mode}")
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
        "removed_models_entries": removed_models,
        "removed_dataset_entries": removed_dataset,
        "archived_training_sources": archived,
        "feature_schema_hash": _schema.get("feature_schema_hash"),
        "feature_schema_version": _schema.get("schema_version"),
        "schema_status": "reset_to_current_runtime_schema",
    }
    _write_json(STATUS_FILE, status)
    return {"ok": True, "backup": backup, "reset": status, "status": ml_status()}
