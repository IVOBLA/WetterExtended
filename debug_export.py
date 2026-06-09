"""24h-Debug-Datenexport als ZIP für das Admin-Panel."""

from __future__ import annotations

import json
import os
import platform
import re
import socket
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from export_security import redact_json_text, redact_text

_TEXT_EXTENSIONS = {".txt", ".log", ".json", ".jsonl", ".csv", ".xml", ".kml", ".py", ".ini", ".cfg", ".conf", ".yaml", ".yml", ".env"}
_ALWAYS_INCLUDE_NAMES = {
    "latest_objects.json",
    "forecast.kmz",
    "latest.png",
    "runtime_overrides.json",
    "config.py",
}
_EXCLUDED_NAMES = {".env", ".admin_password"}
_EXCLUDED_PARTS = {".git", "node_modules", "venv", ".venv", "__pycache__", "frontend/dist"}
_TIMESTAMP_PATTERNS = (
    re.compile(r"(?P<stamp>\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})"),
    re.compile(r"(?P<stamp>\d{8}_\d{6})"),
    re.compile(r"(?P<stamp>\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})"),
    re.compile(r"(?P<stamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?)"),
)
_TIMESTAMP_FORMATS = (
    "%Y-%m-%d_%H-%M-%S",
    "%Y%m%d_%H%M%S",
    "%Y-%m-%dT%H-%M-%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S",
)

@dataclass(frozen=True)
class ExportCandidate:
    src: Path
    section: str
    arc_rel: Path
    force_include: bool = False


def parse_timestamp_from_name(name: str) -> datetime | None:
    for pattern in _TIMESTAMP_PATTERNS:
        match = pattern.search(name)
        if not match:
            continue
        stamp = match.group("stamp")
        for fmt in _TIMESTAMP_FORMATS:
            try:
                parsed = datetime.strptime(stamp, fmt)
                return parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def _git_commit(base_dir: Path) -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(base_dir), text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"


def _safe_rel(path: Path, base_dir: Path) -> Path:
    try:
        return path.resolve().relative_to(base_dir.resolve())
    except Exception:
        return Path(path.name)


def _is_excluded(path: Path, base_dir: Path) -> bool:
    rel = _safe_rel(path, base_dir).as_posix()
    if path.name in _EXCLUDED_NAMES:
        return True
    return any(part in rel.split("/") or rel.startswith(part.rstrip("/") + "/") for part in _EXCLUDED_PARTS)


def _is_text_file(path: Path) -> bool:
    return path.suffix.lower() in _TEXT_EXTENSIONS


def _file_in_window(path: Path, start: datetime, end: datetime, force: bool) -> bool:
    if force or path.name in _ALWAYS_INCLUDE_NAMES:
        return True
    ts = parse_timestamp_from_name(path.name)
    if ts is not None:
        return start <= ts <= end
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        return start <= mtime <= end
    except OSError:
        return False


def _iter_files(root: Path):
    if root.is_file():
        yield root
    elif root.is_dir():
        for path in root.rglob("*"):
            if path.is_file():
                yield path


def _section_for_external(path: Path) -> str:
    parts = [p.lower() for p in path.parts]
    name = path.name.lower()
    joined = "/".join(parts)
    if "external_responses" in parts or "api_call" in name or "api_health" in name:
        return "api_logs" if "api_call" in name or "api_health" in name else "external_responses"
    if "tawes" in joined:
        return "external_responses/geosphere_tawes"
    if "nowcast" in joined:
        return "external_responses/geosphere_nowcast"
    if "eumet" in joined or "cloud" in parts or "sat" in joined:
        return "external_responses/eumetview"
    if "openmeteo" in joined or "open_meteo" in joined or "atmos" in joined or "arome" in parts or "cape" in parts or "wind" in parts:
        return "external_responses/open_meteo"
    if "lightning" in parts or "blitz" in joined:
        return "external_responses/blitz"
    if "hydro" in joined:
        return "external_responses/hydro"
    return "external_responses/other"


def _build_candidates(base_dir: Path, save_paths: dict | None) -> list[ExportCandidate]:
    save_paths = save_paths or {}
    roots: list[tuple[str, Path, bool]] = [
        ("radar", Path(save_paths.get("radar", "train_data/radar")), False),
        ("radar", Path("archiv"), False),
        ("images", Path("data/latest.png"), True),
        ("images", Path("data"), False),
        ("objects", Path(save_paths.get("objects", "train_data/objects")), False),
        ("objects", Path("latest_objects.json"), True),
        ("objects", Path("train_data/tracking"), False),
        ("forecast", Path("forecast.kmz"), True),
        ("forecast", Path("train_data/forecast"), False),
        ("forecast", Path("data/forecast"), False),
        ("evaluation", Path(save_paths.get("evaluation", "train_data/evaluation")), False),
        ("admin_state", Path("train_data/system"), False),
        ("system_logs", Path("logs"), False),
        ("config", Path("config.py"), True),
        ("config", Path("runtime_overrides.json"), True),
    ]
    for key in ("weather", "wind", "cape", "ir", "lightning", "arome", "ir_cells", "system"):
        if key in save_paths:
            roots.append((_section_for_external(Path(save_paths[key])), Path(save_paths[key]), False))
    roots.extend([
        ("external_responses", Path("train_data/external_responses"), False),
        ("external_responses/open_meteo", Path("train_data/weather"), False),
        ("external_responses/open_meteo", Path("train_data/arome"), False),
        ("external_responses/eumetview", Path("train_data/cloud"), False),
        ("external_responses/blitz", Path("train_data/lightning"), False),
    ])
    config_patterns = ("*.json", "*.yaml", "*.yml")
    candidates: dict[Path, ExportCandidate] = {}
    for section, root, force in roots:
        full = root if root.is_absolute() else base_dir / root
        if not full.exists():
            continue
        for file_path in _iter_files(full):
            if _is_excluded(file_path, base_dir):
                continue
            rel = _safe_rel(file_path, base_dir)
            if section == "radar" and root.name == "archiv" and not file_path.name.startswith("radarbild_"):
                continue
            try:
                root_rel = file_path.relative_to(full) if full.is_dir() else Path(file_path.name)
            except Exception:
                root_rel = rel
            if section.startswith("external_responses") or section in {"api_logs", "system_logs", "admin_state"}:
                arc_rel = Path(section) / root_rel
            else:
                arc_rel = Path(section) / rel
            candidates.setdefault(file_path.resolve(), ExportCandidate(file_path, section.split("/")[0], arc_rel, force))
    for pattern in config_patterns:
        for file_path in base_dir.glob(pattern):
            if file_path.is_file() and not _is_excluded(file_path, base_dir):
                candidates.setdefault(file_path.resolve(), ExportCandidate(file_path, "config", Path("config") / file_path.name, True))
    return list(candidates.values())


def _read_redacted(path: Path) -> bytes:
    text = path.read_text(encoding="utf-8", errors="replace")
    redacted = redact_json_text(text) if path.suffix.lower() in {".json", ".jsonl"} else redact_text(text)
    return redacted.encode("utf-8", errors="replace")


def _expected_sections_present(files_by_section: dict[str, int]) -> list[str]:
    expected = {
        "radar": "radar",
        "objects": "objects",
        "forecast": "forecast",
        "evaluation": "evaluation",
        "external_responses": "external_responses",
        "api_logs": "api_logs",
    }
    return [label for section, label in expected.items() if files_by_section.get(section, 0) == 0]


def create_debug_export_zip(*, base_dir: str | Path = ".", save_paths: dict | None = None, hours: int = 24, now: datetime | None = None) -> tuple[Path, str, dict]:
    base_dir = Path(base_dir).resolve()
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    window_start = now - timedelta(hours=hours)
    stamp = now.strftime("%Y-%m-%d_%H-%M-%S")
    root_name = f"wetterextended_debug_{stamp}_last{hours}h"
    filename = f"{root_name}.zip"
    tmp = tempfile.NamedTemporaryFile(prefix="wetterextended_debug_", suffix=".zip", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()

    candidates = _build_candidates(base_dir, save_paths)
    included_roots: set[str] = set()
    excluded_files: list[str] = []
    redacted_files: list[str] = []
    files_by_section: dict[str, int] = {}
    total_bytes = 0
    total_files = 0
    external_sources: set[str] = set()

    with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        readme = (
            "WetterExtended Debug-Export der letzten 24 Stunden\n"
            "Enthält Logs, Bilder, Forecasts, externe Responses und Auswertungsdaten, sofern vorhanden.\n"
            "Textuelle Konfigurationen und Logs wurden auf Secrets geprüft und redacted.\n"
        )
        zf.writestr(f"{root_name}/README.txt", readme)
        for cand in candidates:
            path = cand.src
            rel = _safe_rel(path, base_dir).as_posix()
            if not _file_in_window(path, window_start, now, cand.force_include):
                excluded_files.append(rel)
                continue
            section = cand.section
            arcname = f"{root_name}/{cand.arc_rel.as_posix()}"
            try:
                if _is_text_file(path):
                    data = _read_redacted(path)
                    zf.writestr(arcname, data)
                    total_bytes += len(data)
                    redacted_files.append(rel)
                else:
                    zf.write(path, arcname)
                    total_bytes += path.stat().st_size
                total_files += 1
                files_by_section[section] = files_by_section.get(section, 0) + 1
                included_roots.add(str(cand.arc_rel.parts[0]) if cand.arc_rel.parts else section)
                if "external_responses" in cand.arc_rel.parts:
                    idx = cand.arc_rel.parts.index("external_responses")
                    if len(cand.arc_rel.parts) > idx + 1:
                        external_sources.add(cand.arc_rel.parts[idx + 1])
            except Exception as exc:
                excluded_files.append(f"{rel}: {exc}")

        manifest = {
            "created_at": now.isoformat(timespec="seconds"),
            "window_start": window_start.isoformat(timespec="seconds"),
            "window_end": now.isoformat(timespec="seconds"),
            "hostname": socket.gethostname(),
            "git_commit": _git_commit(base_dir),
            "app_version": os.getenv("WETTEREXTENDED_VERSION", "unknown"),
            "python_version": platform.python_version(),
            "export_reason": "last_24h_debug_run",
            "total_files": total_files,
            "total_bytes": total_bytes,
            "included_roots": sorted(included_roots),
            "excluded_files": sorted(excluded_files),
            "redacted_files": sorted(redacted_files),
            "missing_expected_sections": _expected_sections_present(files_by_section),
            "external_sources_detected": sorted(external_sources),
            "forecast_horizons_min": _extract_forecast_horizons(base_dir),
            "locations_count": _extract_locations_count(base_dir),
            "objects_files_count": files_by_section.get("objects", 0),
            "radar_files_count": files_by_section.get("radar", 0),
            "forecast_files_count": files_by_section.get("forecast", 0),
            "evaluation_files_count": files_by_section.get("evaluation", 0),
        }
        manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
        zf.writestr(f"{root_name}/manifest.json", manifest_bytes)
    manifest["total_files"] = total_files
    return tmp_path, filename, manifest


def _extract_forecast_horizons(base_dir: Path) -> list[int]:
    try:
        import config as cfg
        value = getattr(cfg, "ML_FORECAST_HORIZONS_MIN", [])
        return [int(x) for x in value]
    except Exception:
        return []


def _extract_locations_count(base_dir: Path) -> int:
    try:
        import config as cfg
        value = getattr(cfg, "LOCATIONS_WATCHLIST", [])
        return len(value) if isinstance(value, list) else 0
    except Exception:
        return 0
