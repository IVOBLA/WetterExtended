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
EXPECTED_MAIN_DIRS = ["models", "dataset", "objects", "weather", "hydro", "statistics", "arome", "cape", "cloud", "evaluation", "external_responses", "archived_training_sources"]
MODEL_ARTIFACT_PATTERNS = ["*.keras", "*.h5", "*.joblib", "*.txt", "training_meta.json", "*_metrics.json"]
DATASET_ARTIFACT_PATTERNS = ["*.npz", "*.parquet", "*.csv", "*.pkl", "*.joblib", "*.json"]
TRAINING_SOURCE_KEYS = ("objects", "weather")
PROTECTED_REL = {
    "backups",
    ".env",
    "runtime_overrides.json",
    "train_data/runtime_overrides.json",
    "train_data/statistics",
    "train_data/cell_filters",
    "train_data/dem",
    "train_data/hydro/static",
}
STATIC_HYDRO_CHILDREN = {"static", "generated", "indices", "index", "stations", "catchments", "network", "terrain", "geo", "geography"}
KNOWN_DYNAMIC_DELETE = {"cell_lineage", "lightning", "size_labels", "system", "wind"}
KNOWN_DYNAMIC_DELETE_PATHS = {"hydro/live"}
KNOWN_RUNTIME_STATUS = {"ml_backup_status.json", "ml_reset_status.json"}
KNOWN_CONFIG_PRESERVE = {"runtime_overrides.json", "runtime_overrides.json.bak", "runtime_overrides.json.lock"}
KNOWN_BACKUP_PRESERVE = {"install_backups"}

DYNAMIC_HYDRO_CHILDREN = {"live", "history", "measurements", "timeseries", "impact", "impacts", "verification", "evaluations", "forecast", "forecasts", "nowcast", "nowcasts", "dynamic", "cache", "runtime", "responses", "observations"}
FULL_DELETE_CHILDREN = {"models", "dataset", "objects", "weather", "arome", "cape", "cloud", "evaluation", "external_responses", "archived_training_sources"}
DYNAMIC_NAME_HINTS = ("cache", "raw", "tmp", "temp", "forecast", "nowcast", "radar", "ir", "analysis", "pending", "eval", "verification", "response")
RESET_STEPS = ["preflight", "backup", "validate_backup", "delete_dynamic_data", "verify_delete", "write_status", "finished"]


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



def _section_counts_excluding(path: Path, excluded_rel_paths: set[str], root: Path | None = None) -> dict:
    counts = _section_counts(path, root)
    if not excluded_rel_paths or not (path.exists() or path.is_symlink()):
        return counts
    root = root or PROJECT_ROOT
    files = counts["files"]
    dirs = counts["dirs"]
    bytes_total = counts["bytes"]
    examples = [e for e in counts["examples"] if not any(e == ex or e.startswith(ex + "/") for ex in excluded_rel_paths)]
    for rel in excluded_rel_paths:
        excluded = PROJECT_ROOT / rel
        try:
            is_inside = excluded == path or path.resolve(strict=False) in excluded.resolve(strict=False).parents
        except OSError:
            is_inside = False
        if not is_inside or not (excluded.exists() or excluded.is_symlink()):
            continue
        sub = _section_counts(excluded, root)
        files = max(0, files - sub["files"])
        dirs = max(0, dirs - sub["dirs"] - (1 if excluded.is_dir() and not excluded.is_symlink() else 0))
        bytes_total = max(0, bytes_total - sub["bytes"])
    return {"files": files, "dirs": dirs, "bytes": bytes_total, "size_mb": round(bytes_total / 1024 / 1024, 2), "examples": examples[:8]}

def _action_for_preserved(path: str) -> tuple[str, str]:
    if path == "backups":
        return "preserve_backup", "Root-Backups dürfen niemals automatisch gelöscht werden."
    if path in {".env", "runtime_overrides.json", "train_data/runtime_overrides.json", "train_data/runtime_overrides.json.bak", "train_data/runtime_overrides.json.lock"}:
        return "preserve_config", "Konfigurationen dürfen niemals automatisch gelöscht werden."
    if path == "train_data/install_backups":
        return "preserve_backup", "Installationsbackups bleiben erhalten; Backups sollten künftig im Projekt-Root unter backups/ oder install_backups/ liegen."
    if path == "train_data/statistics":
        return "preserve_statistics", "Langzeitstatistiken bleiben erhalten."
    return "preserve_static_reference", "Statische Referenzdaten bleiben erhalten und werden nicht neu angefordert."


def _section(area: str, path: Path, action: str, root: Path | None = None, reason: str = "", will_recreate: bool = False, protected: bool = False) -> dict:
    safe_root = root or (PROJECT_ROOT if area in {"project", "backups", "config"} else TRAIN_DATA_DIR)
    path = _ensure_inside(path, safe_root)
    counts = _section_counts(path, safe_root)
    return {"area": area, "path": _rel_lexical(path), "action": action, "reason": reason, "will_recreate": will_recreate, "protected": protected, **counts}


def _train_child_section(child: Path, mode: str) -> dict:
    name = child.name
    rel = f"train_data/{name}"
    if rel in PROTECTED_REL:
        action, reason = _action_for_preserved(rel)
        return _section(name, child, action, TRAIN_DATA_DIR, reason, protected=True)
    if mode == "full_new_data_only" and name in KNOWN_DYNAMIC_DELETE:
        return _section(name, child, "delete_after_backup", TRAIN_DATA_DIR, "Bekannter dynamischer ML-/Runtime-/Wetterdatenbereich wird nach validiertem Backup gelöscht.")
    if name == "ml_backup_status.json":
        return _section(name, child, "delete_runtime_status", TRAIN_DATA_DIR, "Backup-Statusdatei blockiert den Reset nicht und wird nach validiertem Backup entfernt.")
    if name == "ml_reset_status.json":
        return _section(name, child, "managed_by_reset_job", TRAIN_DATA_DIR, "Aktive Reset-Statusdatei wird vom laufenden Reset-Job überschrieben und final fortgeführt.", protected=True)
    if name == "ml_job.lock":
        return _section(name, child, "managed_by_reset_job", TRAIN_DATA_DIR, "Aktive ML-Job-Lockdatei wird durch die Job-Sperre verwaltet und blockiert den eigenen Reset-Plan nicht.", protected=True)
    if name in KNOWN_CONFIG_PRESERVE:
        action, reason = _action_for_preserved(rel)
        return _section(name, child, action, TRAIN_DATA_DIR, reason, protected=True)
    if name in KNOWN_BACKUP_PRESERVE:
        action, reason = _action_for_preserved(rel)
        sec = _section(name, child, action, TRAIN_DATA_DIR, reason, protected=True)
        sec["warning"] = "train_data/install_backups liegt innerhalb von train_data. Backups sollten künftig im Projekt-Root unter backups/ oder install_backups/ liegen."
        return sec
    if (mode == "models_only" and name in {"models", "dataset"}) or (mode == "full_new_data_only" and name in FULL_DELETE_CHILDREN):
        return _section(name, child, "delete_after_backup", TRAIN_DATA_DIR, "Dynamische ML-/Rohdaten-/Cache-/Evaluationshistorie wird nach validiertem Backup gelöscht.", will_recreate=name in {"models", "dataset", "objects", "weather"})
    if name == "hydro":
        return _section("hydro", child, "container_only", TRAIN_DATA_DIR, "mixed_hydro_container_children_are_classified_individually", protected=True)
    if name in {"statistics", "cell_filters", "dem"}:
        action, reason = _action_for_preserved(rel)
        return _section(name, child, action, TRAIN_DATA_DIR, reason, protected=True)
    if name == "runtime_overrides.json":
        action, reason = _action_for_preserved(rel)
        return _section(name, child, action, TRAIN_DATA_DIR, reason, protected=True)
    if mode == "full_new_data_only" and any(h in name.lower() for h in DYNAMIC_NAME_HINTS):
        return _section(name, child, "delete_after_backup", TRAIN_DATA_DIR, "Name deutet auf dynamische Cache-/Analyse-/Forecast-Daten hin; Löschung erst nach validiertem Backup.")
    return _section(name, child, "manual_review_required", TRAIN_DATA_DIR, "Unbekannter train_data-Bereich: keine automatische Löschung ohne klare Klassifikation.")


def _hydro_child_section(child: Path, mode: str) -> dict:
    name = child.name.lower()
    rel = f"train_data/hydro/{child.name}"
    if child.is_file() or rel == "train_data/hydro/static" or name in STATIC_HYDRO_CHILDREN:
        return _section(f"hydro/{child.name}", child, "preserve_static_reference", TRAIN_DATA_DIR, "static_hydro_reference_data" if rel == "train_data/hydro/static" else "Statische Hydro-/Geografie-/Terrain-Referenzdaten bleiben erhalten.", protected=rel == "train_data/hydro/static")
    if mode == "full_new_data_only" and (f"hydro/{child.name}" in KNOWN_DYNAMIC_DELETE_PATHS or name in DYNAMIC_HYDRO_CHILDREN or any(h in name for h in DYNAMIC_NAME_HINTS)):
        reason = "dynamic_hydro_live_data" if name == "live" else "Dynamische Hydro-Messreihe/-Impact-/-Verification-Historie wird gelöscht."
        return _section(f"hydro/{child.name}", child, "delete_after_backup", TRAIN_DATA_DIR, reason)
    return _section(f"hydro/{child.name}", child, "manual_review_required", TRAIN_DATA_DIR, "Hydro-Unterordner ist fachlich nicht eindeutig klassifizierbar.")


def build_reset_plan(mode: str) -> dict:
    if mode not in RESET_MODES:
        raise ValueError(f"Ungueltiger Reset-Modus: {mode}")
    TRAIN_DATA_DIR.mkdir(parents=True, exist_ok=True)
    root_preserved = []
    for path in [BACKUP_DIR, PROJECT_ROOT / ".env", PROJECT_ROOT / "runtime_overrides.json"]:
        rel = _rel_lexical(path)
        action, reason = _action_for_preserved(rel)
        root_preserved.append(_section(path.name or rel, path, action, PROJECT_ROOT, reason, protected=True))
    preserve_sections = []
    delete_sections = []
    delete_children_sections = []
    manual_review_sections = []
    protected_sections = list(root_preserved)
    managed_sections = []
    warnings = []
    for child in sorted(TRAIN_DATA_DIR.iterdir(), key=lambda p: p.name) if TRAIN_DATA_DIR.exists() else []:
        sec = _train_child_section(child, mode)
        if sec["action"] in {"delete_after_backup", "delete_runtime_status"}:
            delete_sections.append(sec)
        elif sec["action"] in {"delete_children_after_backup", "container_only"}:
            if sec["action"] == "delete_children_after_backup":
                delete_children_sections.append(sec)
            else:
                preserve_sections.append(sec)
                protected_sections.append(sec)
            if child.name == "hydro" and child.is_dir() and not child.is_symlink():
                for hchild in sorted(child.iterdir(), key=lambda p: p.name):
                    hsec = _hydro_child_section(hchild, mode)
                    if hsec["action"] == "delete_after_backup":
                        delete_sections.append(hsec)
                    elif hsec["action"] == "manual_review_required":
                        manual_review_sections.append(hsec)
                    else:
                        preserve_sections.append(hsec)
                        if hsec.get("protected"):
                            protected_sections.append(hsec)
        elif sec["action"] == "manual_review_required":
            manual_review_sections.append(sec)
        elif sec["action"] == "managed_by_reset_job":
            managed_sections.append(sec)
            if sec.get("protected"):
                protected_sections.append(sec)
        else:
            preserve_sections.append(sec)
            if sec.get("warning"):
                warnings.append(sec["warning"])
            if sec.get("protected"):
                protected_sections.append(sec)
    # Show missing but protected important paths in preview.
    for rel in ["train_data/runtime_overrides.json", "train_data/statistics", "train_data/cell_filters", "train_data/dem", "train_data/hydro/static"]:
        path = PROJECT_ROOT / rel
        if not any(s["path"] == rel for s in preserve_sections + protected_sections):
            action, reason = _action_for_preserved(rel)
            sec = _section(Path(rel).name, path, action, PROJECT_ROOT if not rel.startswith("train_data/") else TRAIN_DATA_DIR, reason, protected=True)
            preserve_sections.append(sec); protected_sections.append(sec)
    sections = delete_sections + delete_children_sections + managed_sections + preserve_sections + manual_review_sections + root_preserved
    delete_summary = _sum_sections(delete_sections + delete_children_sections)
    preserve_summary = _sum_sections(preserve_sections + root_preserved)
    manual_summary = _sum_sections(manual_review_sections)
    summary = {
        "delete_files": delete_summary["files"],
        "delete_dirs": delete_summary["dirs"],
        "delete_bytes": delete_summary["bytes"],
        "delete_size_mb": delete_summary["size_mb"],
        "preserve_files": preserve_summary["files"],
        "preserve_dirs": preserve_summary["dirs"],
        "preserve_bytes": preserve_summary["bytes"],
        "preserve_size_mb": preserve_summary["size_mb"],
        "manual_review_files": manual_summary["files"],
        "manual_review_dirs": manual_summary["dirs"],
        "manual_review_bytes": manual_summary["bytes"],
        "manual_review_size_mb": manual_summary["size_mb"],
        "managed_files": _sum_sections(managed_sections)["files"],
        "managed_dirs": _sum_sections(managed_sections)["dirs"],
    }
    return {
        "mode": mode,
        "created_at": _utc_now().isoformat(),
        "project_root": str(PROJECT_ROOT),
        "train_data_root": str(TRAIN_DATA_DIR),
        "backup": {"will_create": True, "target_dir": "backups", "target": "backups/YYYYMMDD_HHMMSS_train_data.zip", "protected": True},
        "sections": sections,
        "summary": summary,
        "will_backup": True,
        "backup_target": "backups/YYYYMMDD_HHMMSS_train_data.zip",
        "preserve_sections": preserve_sections,
        "preserved_sections": preserve_sections,
        "delete_sections": delete_sections,
        "delete_children_sections": delete_children_sections,
        "manual_review_sections": manual_review_sections,
        "managed_sections": managed_sections,
        "runtime_status_sections": managed_sections,
        "protected_sections": protected_sections,
        "warnings": warnings,
        "archive_sections": [],
    }

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



def _is_hydro_static_or_parent(rel: str) -> bool:
    return rel == "train_data/hydro" or rel == "train_data/hydro/static" or rel.startswith("train_data/hydro/static/")


def _assert_delete_plan_safe(plan: dict) -> None:
    forbidden = set(PROTECTED_REL) | {".", "train_data"}
    for sec in plan.get("delete_sections", []) + plan.get("delete_children_sections", []):
        rel = sec.get("path", "")
        action = sec.get("action")
        if action not in {"delete_after_backup", "delete_children_after_backup", "delete_runtime_status"}:
            continue
        if _is_hydro_static_or_parent(rel):
            raise RuntimeError("Hydro static reference data must not be deleted. Classify hydro children individually.")
        if rel in forbidden or any(rel == p or rel.startswith(p + "/") and p in {"backups"} for p in forbidden):
            raise RuntimeError(f"Geschützter Pfad im Löschplan: {rel}")
        path = PROJECT_ROOT / rel
        _ensure_inside(path, TRAIN_DATA_DIR)
        if path.resolve(strict=False) in {PROJECT_ROOT.resolve(strict=False), TRAIN_DATA_DIR.resolve(strict=False)}:
            raise RuntimeError(f"Unsicherer Löschpfad: {rel}")


def _delete_section(sec: dict) -> dict:
    path = PROJECT_ROOT / sec["path"]
    before = _section(sec.get("area", path.name), path, sec.get("action", "delete_after_backup"), PROJECT_ROOT if not sec["path"].startswith("train_data/") else TRAIN_DATA_DIR, sec.get("reason", ""), sec.get("will_recreate", False), sec.get("protected", False))
    if path.exists() or path.is_symlink():
        _safe_unlink(path, TRAIN_DATA_DIR)
    if sec.get("will_recreate"):
        path.mkdir(parents=True, exist_ok=True)
    after = _section_counts(path, TRAIN_DATA_DIR) if (path.exists() or path.is_symlink()) else {"files": 0, "dirs": 0, "bytes": 0, "size_mb": 0.0, "examples": []}
    return before | {"after": after, "verified_empty": after["files"] == 0 and after["dirs"] == 0}


def _execute_delete_plan(plan: dict) -> list[dict]:
    _assert_delete_plan_safe(plan)
    deleted = []
    for sec in plan.get("delete_sections", []):
        deleted.append(_delete_section(sec))
    return deleted


def verify_reset_result(execution_plan: dict) -> dict:
    checked_at = _utc_now().isoformat()
    deleted_verified = []
    preserved_verified = []
    leftovers_files = leftovers_dirs = leftovers_bytes = 0
    preserved_paths = {s.get("path", "") for s in execution_plan.get("preserve_sections", []) + execution_plan.get("protected_sections", []) if s.get("action", "").startswith("preserve_") or s.get("protected")}
    for sec in execution_plan.get("delete_sections", []) + execution_plan.get("delete_children_sections", []):
        if sec.get("action") == "container_only":
            continue
        path = PROJECT_ROOT / sec["path"]
        excluded = {p for p in preserved_paths if p and (p == sec["path"] or p.startswith(sec["path"].rstrip("/") + "/"))}
        counts = _section_counts_excluding(path, excluded, TRAIN_DATA_DIR) if (path.exists() or path.is_symlink()) else {"files": 0, "dirs": 0, "bytes": 0, "size_mb": 0.0, "examples": []}
        ok = counts["files"] == 0 and counts["dirs"] == 0
        if not ok:
            leftovers_files += counts["files"]
            leftovers_dirs += counts["dirs"]
            leftovers_bytes += counts["bytes"]
        deleted_verified.append({
            "path": sec["path"],
            "expected": "empty_or_missing",
            "exists": path.exists() or path.is_symlink(),
            "actual_files": counts["files"],
            "actual_dirs": counts["dirs"],
            "actual_bytes": counts["bytes"],
            "actual_size_mb": counts["size_mb"],
            "ok": ok,
            "leftovers": counts["examples"],
        })
    for sec in execution_plan.get("preserve_sections", []) + execution_plan.get("protected_sections", []):
        path = PROJECT_ROOT / sec["path"]
        if sec["path"].startswith("train_data/"):
            path = PROJECT_ROOT / sec["path"]
        exists = path.exists() or path.is_symlink()
        counts = _section_counts(path, PROJECT_ROOT if not sec["path"].startswith("train_data/") else TRAIN_DATA_DIR) if exists else {"files": 0, "dirs": 0, "bytes": 0, "size_mb": 0.0, "examples": []}
        preserved_verified.append({
            "path": sec["path"],
            "exists": exists,
            "actual_files": counts["files"],
            "actual_dirs": counts["dirs"],
            "actual_bytes": counts["bytes"],
            "actual_size_mb": counts["size_mb"],
            "ok": exists or int(sec.get("files") or 0) == 0 and int(sec.get("dirs") or 0) == 0,
        })
    leftovers_total = {"files": leftovers_files, "dirs": leftovers_dirs, "bytes": leftovers_bytes, "size_mb": round(leftovers_bytes / 1024 / 1024, 2)}
    return {
        "verification_status": "passed" if leftovers_files == 0 and leftovers_dirs == 0 else "leftovers",
        "checked_at": checked_at,
        "deleted_sections_verified": deleted_verified,
        "preserved_sections_verified": preserved_verified,
        "leftovers_total": leftovers_total,
    }

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
    plan = _read_json(STATUS_FILE).get("execution_plan") or {}
    try:
        if not plan:
            plan = build_reset_plan(mode)
        _mark_reset_step("preflight", job_id, pid=os.getpid(), mode=mode, execution_plan=plan, plan=plan)
        if mode == "full_new_data_only" and plan.get("manual_review_sections"):
            raise RuntimeError("Manuelle Prüfung erforderlich: " + ", ".join(s.get("path", "") for s in plan["manual_review_sections"]))
        _assert_delete_plan_safe(plan)
        _mark_reset_step("backup", job_id)
        backup = create_backup(mode)
        _mark_reset_step("validate_backup", job_id, backup=backup)
        validation = validate_backup(BACKUP_DIR / backup["id"])
        if not validation.get("valid"):
            raise RuntimeError("Backup-Validierung fehlgeschlagen: " + "; ".join(validation.get("errors") or []))
        _mark_reset_step("delete_dynamic_data", job_id, backup=backup)
        deleted_sections = _execute_delete_plan(plan)
        _mark_reset_step("verify_delete", job_id)
        verification = verify_reset_result(plan)
        archived = []
        try:
            from feature_schema import get_current_feature_schema
            _schema = get_current_feature_schema()
        except Exception:
            _schema = {}
        deleted_counts = _sum_sections(deleted_sections)
        archived_counts = _sum_sections(archived)
        result = {
            "status": "reset_done", "mode": mode, "backup": backup.get("path"), "backup_id": backup.get("id"),
            "backup_size_mb": backup.get("size_mb"), "created": _utc_now().isoformat(),
            "next_action": "collect_new_data" if mode == "full_new_data_only" else "rebuild_dataset_or_retrain",
            "feature_schema_hash": _schema.get("feature_schema_hash"), "feature_schema_version": _schema.get("schema_version"),
            "schema_status": "reset_to_current_runtime_schema",
            "fallback": "ML-Modell fehlt, kinematischer Fallback aktiv, neue Trainingsdaten werden ab jetzt gesammelt.",
        }
        final_status = "finished" if verification.get("verification_status") == "passed" else "completed_with_leftovers"
        _mark_reset_step("write_status", job_id, result=result, deleted_counts=deleted_counts, archived_counts=archived_counts, verification=verification)
        _reset_status_payload(status=final_status, running=False, finished=final_status == "finished", failed=final_status != "finished", job_id=job_id, pid=os.getpid(), mode=mode, finished_at=_utc_now().isoformat(), current_step="finished" if final_status == "finished" else "verify_delete", progress="Reset abgeschlossen" if final_status == "finished" else "Reset mit Restdaten abgeschlossen", percent=100, error=None if final_status == "finished" else "Abschlussprüfung fand Restdaten.", execution_plan=plan, plan=plan, backup=backup, result=result, delete_result={"deleted_sections": deleted_sections, "deleted_counts": deleted_counts}, deleted_counts=deleted_counts, archived_counts=archived_counts, verification=verification, preserved_sections=plan.get("preserved_sections", []))
    except Exception as exc:
        message = str(exc)
        failure_status = "failed_safety_check" if "Geschützter Pfad" in message or "Manuelle Prüfung" in message or "Unsicherer Löschpfad" in message or "Hydro static reference data" in message else "failed_delete"
        if "Backup" in message or "backup" in message:
            failure_status = "failed_backup"
        _reset_status_payload(status=failure_status, running=False, finished=False, failed=True, job_id=job_id, pid=os.getpid(), mode=mode, finished_at=_utc_now().isoformat(), current_step="failed", progress="Reset fehlgeschlagen", error=message, execution_plan=plan, plan=plan)
    finally:
        _release_ml_job_lock(owner)


def start_reset_background(mode: str, force: bool = False) -> dict:
    if mode not in RESET_MODES:
        raise ValueError(f"Ungueltiger Reset-Modus: {mode}")
    current = _lock_owner()
    if current:
        raise RuntimeError(f"ML-Job läuft bereits: {current.get('kind', 'unknown')}")
    if _training_running():
        raise RuntimeError("Training läuft bereits")
    job_id = f"reset_{_utc_now().strftime('%Y%m%d_%H%M%S_%f')}"
    plan = build_reset_plan(mode)
    if plan.get("manual_review_sections") and not force:
        raise ValueError("Manuelle Prüfung erforderlich: " + ", ".join(s.get("path", "") for s in plan["manual_review_sections"]))
    owner = _acquire_ml_job_lock("reset", job_id)
    _reset_status_payload(status="starting", running=True, finished=False, failed=False, job_id=job_id, pid=None, mode=mode, started_at=_utc_now().isoformat(), finished_at=None, current_step="preflight", progress="Reset wird gestartet", percent=0, error=None, execution_plan=plan, plan=plan, backup={}, delete_result={}, result=None, deleted_counts=None, archived_counts=None, verification={}, preserved_sections=plan.get("preserved_sections", []))
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
        plan = build_reset_plan(mode)
        if mode == "full_new_data_only" and plan.get("manual_review_sections"):
            raise RuntimeError("Manuelle Prüfung erforderlich: " + ", ".join(s.get("path", "") for s in plan["manual_review_sections"]))
        _assert_delete_plan_safe(plan)
        backup = create_backup(mode)
        validation = validate_backup(BACKUP_DIR / backup["id"])
        if not validation.get("valid"):
            raise RuntimeError("Backup-Validierung fehlgeschlagen: " + "; ".join(validation.get("errors") or []))
        deleted_sections = _execute_delete_plan(plan)
        verification = verify_reset_result(plan)
        archived = []
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
            "removed_models_entries": 0,
            "removed_dataset_entries": 0,
            "deleted_counts": _sum_sections(deleted_sections),
            "archived_counts": _sum_sections(archived),
            "archived_training_sources": archived,
            "preserved_sections": plan.get("preserve_sections", []),
            "execution_plan": plan,
            "verification": verification,
            "feature_schema_hash": _schema.get("feature_schema_hash"),
            "feature_schema_version": _schema.get("schema_version"),
            "schema_status": "reset_to_current_runtime_schema",
        }
        status["status"] = "reset_done" if verification.get("verification_status") == "passed" else "completed_with_leftovers"
        _write_json(STATUS_FILE, status)
        return {"ok": True, "backup": backup, "reset": status, "status": ml_status()}
    finally:
        _release_ml_job_lock(owner)
