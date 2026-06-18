"""24h-Debug-Datenexport als ZIP für das Admin-Panel."""

from __future__ import annotations

import json
import os
import platform
import re
import socket
import subprocess
import tempfile
import time
import zipfile
import zlib  # B128: komprimierte Größenschätzung für Volume-Aufteilung
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from export_security import redact_json_text, redact_text

# DIAGNOSE B115: Export-Absturz-Analyse
# Wahrscheinliche Ursache: unbehandelte Exception oder OOM beim Log-Read.
# Nginx-Error-Log mit "upstream prematurely closed connection" stand nicht zur Verfügung.
# Gesicherter Befund: Prozess für 2 min tot nach Export-Aufruf (Log 10:45–10:47 CEST).
# Fix: alle Exceptions fangen, journalctl mit Timeout, Log-Reads size-begrenzt, ZIP auf Disk.

# B140: Frühere 50-MB-Byte-Hartgrenze entfernt.
# Es gibt KEINE Byte-Gesamtgrenze mehr — maßgeblich ist ausschließlich die
# komprimierte Volume-Größe (siehe Volume-Splitting / B128).
# B126: Maximale Größe je ZIP-Volume. Der Gesamtexport wird verlustfrei auf
# mehrere Volumes <= dieser Grenze aufgeteilt (kein Datei-Weglassen).
EXPORT_VOLUME_MAX_BYTES = int(os.getenv("DEBUG_EXPORT_VOLUME_MAX_BYTES", str(80 * 1024 * 1024)))
# B128: fester Volume-Dateiname-Stamm → wetterextended_debug1.zip, …debug2.zip, …
EXPORT_VOLUME_BASENAME = os.getenv("DEBUG_EXPORT_VOLUME_BASENAME", "wetterextended_debug")
# B128: ZIP-Overhead-Reserve, damit die KOMPRIMIERTE Volumegröße das Limit nie überschreitet.
_ZIP_ENTRY_OVERHEAD = 120     # lokaler Header + Central-Directory-Eintrag (Bytes), konservativ
_ZIP_TRAILER_OVERHEAD = 1024  # End-of-Central-Directory + Reserve
_PRIORITY_TEXT_EXTS = {
    ".json", ".jsonl", ".csv", ".txt", ".log", ".kml", ".xml",
    ".py", ".ini", ".cfg", ".conf", ".yaml", ".yml", ".env",
}
_NGINX_TAIL_BYTES = 5 * 1024 * 1024

_TEXT_EXTENSIONS = {".txt", ".log", ".json", ".jsonl", ".csv", ".xml", ".kml", ".py", ".ini", ".cfg", ".conf", ".yaml", ".yml", ".env"}
_ALWAYS_INCLUDE_NAMES = {
    "latest_objects.json",
    "forecast.kmz",
    "latest.png",
    "runtime_overrides.json",
    "motion_pipeline_health.json",
    "drift_status.json",
    "accuracy_history.jsonl",
    "forecast_error_details.jsonl",
    "forecast_error_diagnosis.json",
    "config.py",
}
_EXCLUDED_NAMES = {".admin_password"}
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


class ExportLimitExceeded(RuntimeError):
    """Der Debug-Export wurde wegen konfigurierter Schutzgrenzen abgebrochen."""


def _estimated_zip_entry_bytes(data: bytes, arcname: str) -> int:
    """B128: Schätzt die KOMPRIMIERTE Größe eines ZIP-Eintrags (Deflate, identisch
    zu ZIP_DEFLATED-Default) inkl. Header-Overhead. Grundlage für die Aufteilung
    nach komprimierter Größe — die unkomprimierte Größe spielt keine Rolle."""
    try:
        co = zlib.compressobj(zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, -15)
        body = len(co.compress(data)) + len(co.flush())
    except Exception:
        body = len(data)
    # B139: ZIP-Header speichern die UTF-8-BYTELÄNGE des Namens (nicht Zeichen),
    # und zwar 2× (lokaler Header + Central Directory). Bei ä/Emoji/langen Pfaden
    # verhindert die Bytelänge ein Überschreiten des Volume-Limits.
    try:
        _name_bytes = len(arcname.encode("utf-8"))
    except Exception:
        _name_bytes = len(arcname)
    return body + _ZIP_ENTRY_OVERHEAD + 2 * _name_bytes


def _volume_priority(arcname: str) -> int:
    """0 = Text/Diagnose (zuerst), 1 = Binär/Rest (später)."""
    ext = os.path.splitext(arcname)[1].lower()
    return 0 if (ext in _PRIORITY_TEXT_EXTS or arcname.endswith(".env")) else 1


def create_debug_export_volumes(
    base_dir,
    save_paths: dict | None = None,
    hours: int = 24,
    now: "datetime | None" = None,
    max_files: int = 50000,   # B142
    volume_max_bytes: int = EXPORT_VOLUME_MAX_BYTES,
    out_dir: str | Path | None = None,
) -> "tuple[list[tuple[Path, str]], dict]":
    """B126: Baut den VOLLSTÄNDIGEN Export und teilt ihn VERLUSTFREI in
    ZIP-Volumes <= volume_max_bytes auf. KEINE Datei wird weggelassen.

    Rückgabe: (parts, manifest) mit parts = [(Path, filename), ...] in Reihenfolge
    part01ofNN … partNNofNN. Single-File > volume_max_bytes bekommt ein eigenes
    Volume; ansonsten wird vor Überschreiten der KOMPRIMIERTEN Volumegröße
    (Deflate-Schätzung inkl. UTF-8-Header-Bytelänge) ein neues Volume begonnen.
    """
    now = now or datetime.now(timezone.utc)
    out_dir = Path(out_dir) if out_dir else Path(tempfile.mkdtemp(prefix="wetterextended_vol_"))
    out_dir.mkdir(parents=True, exist_ok=True)

    full_fd = tempfile.NamedTemporaryFile(prefix="wetterextended_full_", suffix=".zip", delete=False)
    full_path = Path(full_fd.name)
    full_fd.close()
    try:
        src_path, base_filename, manifest = create_debug_export_zip(
            base_dir=base_dir, save_paths=save_paths, hours=hours, now=now,
            max_files=max_files, max_total_bytes=None, tmp_path=full_path,
        )
    except BaseException:
        # B140: Bei Fehler im Vollexport die bereits angelegte Temp-Datei nicht leaken.
        full_path.unlink(missing_ok=True)
        raise
    src_path = Path(src_path)
    root_stem = base_filename[:-4] if base_filename.lower().endswith(".zip") else base_filename

    parts: list[tuple[Path, str]] = []
    try:
        with zipfile.ZipFile(src_path, "r") as src:
            infos = sorted(src.infolist(), key=lambda zi: (_volume_priority(zi.filename), zi.filename))
            part_idx = 0
            cur_zip = None
            cur_path = None
            cur_est = 0      # B128: geschätzte KOMPRIMIERTE Größe des aktuellen Volumes
            cur_count = 0    # Anzahl Einträge im aktuellen Volume

            def _open_new_part():
                nonlocal part_idx, cur_zip, cur_path, cur_est, cur_count
                part_idx += 1
                cur_path = out_dir / f"{root_stem}_part{part_idx:02d}.zip"
                cur_zip = zipfile.ZipFile(cur_path, "w", compression=zipfile.ZIP_DEFLATED)
                cur_est = _ZIP_TRAILER_OVERHEAD
                cur_count = 0

            _open_new_part()
            for zi in infos:
                data = src.read(zi.filename)
                # B128: NUR die komprimierte Volumegröße begrenzt — unkomprimiert ist egal.
                est = _estimated_zip_entry_bytes(data, zi.filename)
                if cur_count > 0 and cur_est + est > volume_max_bytes:
                    cur_zip.close()
                    parts.append((cur_path, cur_path.name))
                    _open_new_part()
                cur_zip.writestr(zi, data)
                cur_est += est
                cur_count += 1
            cur_zip.close()
            parts.append((cur_path, cur_path.name))
    finally:
        src_path.unlink(missing_ok=True)

    total = len(parts)
    final_parts: list[tuple[Path, str]] = []
    for i, (p, _name) in enumerate(parts, start=1):
        # B128: durchnummeriert ohne Timestamp/Padding → wetterextended_debug{N}.zip
        final_name = f"{EXPORT_VOLUME_BASENAME}{i}.zip"
        final_path = p.with_name(final_name)
        p.rename(final_path)
        final_parts.append((final_path, final_name))

    manifest = dict(manifest)
    manifest["part_count"] = total
    manifest["volume_max_bytes"] = volume_max_bytes
    manifest["parts"] = [
        {"index": i, "filename": n, "bytes": fp.stat().st_size}
        for i, (fp, n) in enumerate(final_parts, start=1)
    ]
    return final_parts, manifest


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
    if path.suffix.lower() == ".zip" and ("/" not in rel or rel.startswith("data/")):
        return True
    return any(part in rel.split("/") or rel.startswith(part.rstrip("/") + "/") for part in _EXCLUDED_PARTS)


def _is_text_file(path: Path) -> bool:
    return path.name == ".env" or path.suffix.lower() in _TEXT_EXTENSIONS


def _file_in_window(path: Path, start: datetime, end: datetime, force: bool) -> bool:
    if force or path.name in _ALWAYS_INCLUDE_NAMES:
        return True
    # B142: st_mtime (UTC) ist die EINZIGE zeitzonensichere Fensterbasis.
    # radar/objects/locations-Dateinamen sind Europe/Vienna-Lokalzeit (B122);
    # parse_timestamp_from_name() interpretierte sie als UTC (+2 h CEST), wodurch die
    # jüngsten Frames als "Zukunft" aus dem 24h-Fenster fielen. Schreibzeit ≈ Aufnahmezeit.
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


def _build_candidates_with_diagnostics(base_dir: Path, save_paths: dict | None) -> tuple[list[ExportCandidate], dict]:
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
        ("cell_lineage", Path("train_data/cell_lineage"), False),
        ("system_logs", Path("logs"), False),
        ("config", Path("config.py"), True),
        ("config", Path("runtime_overrides.json"), True),
    ]
    for key in ("weather", "wind", "cape", "ir", "lightning", "arome", "ir_cells", "system", "cell_lineage"):
        if key in save_paths:
            roots.append((_section_for_external(Path(save_paths[key])), Path(save_paths[key]), False))
    roots.extend([
        ("external_responses", Path("train_data/external_responses"), False),
        ("external_responses/open_meteo", Path("train_data/weather"), False),
        ("external_responses/open_meteo", Path("train_data/arome"), False),
        ("external_responses/eumetview", Path("train_data/cloud"), False),
        ("external_responses/blitz", Path("train_data/lightning"), False),
    ])
    config_patterns = ("*.json", "*.yaml", "*.yml", ".env")
    candidates: dict[Path, ExportCandidate] = {}
    scanned_roots: list[str] = []
    excluded_files_count = 0
    for section, root, force in roots:
        full = root if root.is_absolute() else base_dir / root
        if not full.exists():
            continue
        scanned_roots.append(str(full))
        for file_path in _iter_files(full):
            if _is_excluded(file_path, base_dir):
                excluded_files_count += 1
                continue
            rel = _safe_rel(file_path, base_dir)
            if section == "radar" and root.name == "archiv" and not file_path.name.startswith("radarbild_"):
                excluded_files_count += 1
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
            elif file_path.is_file():
                excluded_files_count += 1
    # B142: Früheres B115-Pruning (nur 3 neueste Dateien je train_data-Unterverzeichnis)
    # ERSATZLOS entfernt. Es kürzte radar/objects UND die Wetterdaten (weather/cape/arome/
    # external_responses) auf 3 Snapshots — die KI braucht aber das vollständige 24h-Fenster.
    # Die einzige Grenze ist jetzt _file_in_window (24h); die Größe regelt der Volume-Split
    # (B128, komprimiert). Keine Kürzung mehr.

    diagnostics = {
        "candidates_count": len(candidates),
        "scanned_roots": sorted(scanned_roots),
        "excluded_files_count": excluded_files_count,
    }
    return list(candidates.values()), diagnostics


def _build_candidates(base_dir: Path, save_paths: dict | None) -> list[ExportCandidate]:
    candidates, _diagnostics = _build_candidates_with_diagnostics(base_dir, save_paths)
    return candidates


def _read_redacted(path: Path) -> bytes:
    text = path.read_text(encoding="utf-8", errors="replace")
    redacted = redact_json_text(text) if path.suffix.lower() in {".json", ".jsonl"} else redact_text(text)
    return redacted.replace("***REDACTED***", "<REDACTED>").encode("utf-8", errors="replace")


def _journalctl_export_text(unit: str, window_start: datetime, now: datetime) -> tuple[str, bool]:
    if not shutil.which("journalctl"):
        return f"[journalctl] journalctl nicht verfügbar; {unit}.service konnte nicht gelesen werden.\n", False
    # B135: --since/--until als UTC-Epoch (@<sek>). Reine Datums-Strings würden von
    # journalctl als LOKALZEIT (CEST) interpretiert → Fenster 2h verschoben.
    # -n liefert die NEUESTEN N Zeilen im Fenster (zuvor --lines 2000 ohne --until →
    # älteste 2000 Zeilen; die neueren ~21h des verbosen Hauptdienstes fehlten im Export).
    from datetime import timezone as _tz_b135

    def _epoch(dt: datetime) -> int:
        dt_utc = dt if dt.tzinfo is not None else dt.replace(tzinfo=_tz_b135.utc)
        return int(dt_utc.timestamp())

    cmd = [
        "journalctl", "-u", unit,
        "--since", f"@{_epoch(window_start)}",
        "--until", f"@{_epoch(now)}",
        "-n", "5000",
        "--no-pager",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=False)
    except Exception as exc:
        return f"[journalctl] Fehler beim Lesen von {unit}.service: {exc}\n", False
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        details = f" Details: {stderr}" if stderr else ""
        return f"[journalctl] {unit}.service nicht verfügbar oder nicht lesbar.{details}\n", False
    return result.stdout or f"[journalctl] Keine Einträge für {unit}.service im Exportzeitraum.\n", True


_NGINX_TS_RE = re.compile(r"\[(?P<stamp>\d{2}/[A-Za-z]{3}/\d{4}:\d{2}:\d{2}:\d{2})(?: [+-]\d{4})?\]")


def _nginx_line_in_window(line: str, window_start: datetime, now: datetime) -> bool:
    match = _NGINX_TS_RE.search(line)
    if not match:
        return True
    try:
        parsed = datetime.strptime(match.group("stamp"), "%d/%b/%Y:%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return window_start <= parsed <= now


def _read_nginx_log_for_export(path: Path, window_start: datetime | None = None, now: datetime | None = None) -> tuple[str, bool]:
    try:
        lines: list[str] = []
        with path.open("rb") as fh:
            try:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                fh.seek(max(0, size - _NGINX_TAIL_BYTES), os.SEEK_SET)
            except OSError:
                fh.seek(0)
            raw = fh.read(_NGINX_TAIL_BYTES)
        for line in raw.decode("utf-8", errors="replace").splitlines():
            if window_start is not None and now is not None and not _nginx_line_in_window(line, window_start, now):
                continue
            lines.append(line)
    except (PermissionError, FileNotFoundError):
        return f"source_unavailable: {path}\n", False
    except OSError as exc:
        return f"source_unavailable: {path}: {exc}\n", False
    text = "\n".join(lines)
    if text:
        text += "\n"
    return text or f"[nginx] Keine Einträge in {path} im Exportzeitraum.\n", True


def _project_log_candidates(base_dir: Path, save_paths: dict | None) -> list[Path]:
    roots = [base_dir / "logs", base_dir / "train_data" / "evaluation"]
    for raw in (save_paths or {}).values():
        try:
            roots.append(Path(raw) if Path(raw).is_absolute() else base_dir / Path(raw))
        except Exception:
            continue
    candidates: dict[Path, Path] = {}
    for root in roots:
        if not root.exists():
            continue
        for pattern in ("*.log", "*.txt", "*.jsonl"):
            for path in root.rglob(pattern) if root.is_dir() else []:
                lname = path.name.lower()
                if any(token in lname for token in ("api", "debug", "error", "log", "health")):
                    candidates[path.resolve()] = path
    return list(candidates.values())


def _write_api_logs_to_zip(zf: zipfile.ZipFile, root_name: str, base_dir: Path, save_paths: dict | None, window_start: datetime, now: datetime) -> dict:
    files_count = 0
    total_bytes = 0
    redacted: list[str] = []
    unavailable: list[str] = []
    journal_success = False
    nginx_success = False

    def write_text(arc_rel: str, text: str, redact: bool = True):
        nonlocal files_count, total_bytes
        payload = redact_text(text).replace("***REDACTED***", "<REDACTED>") if redact else text
        data = payload.encode("utf-8", errors="replace")
        zf.writestr(f"{root_name}/api_logs/{arc_rel}", data)
        files_count += 1
        total_bytes += len(data)
        if redact:
            redacted.append(f"api_logs/{arc_rel}")

    for unit in ("wetterprojekt", "wetterprojekt-scheduler", "wetterprojekt-admin"):
        text, ok = _journalctl_export_text(unit, window_start, now)
        journal_success = journal_success or ok
        if not ok:
            unavailable.append(f"{unit}.service")
        write_text(f"journal/{unit}.service.log", text)

    for label, raw_path in (("nginx_error", "/var/log/nginx/error.log"), ("nginx_access", "/var/log/nginx/access.log")):
        text, ok = _read_nginx_log_for_export(Path(raw_path), window_start, now)
        nginx_success = nginx_success or ok
        if not ok:
            unavailable.append(raw_path)
        write_text(f"nginx/{label}.log", text)

    for path in _project_log_candidates(base_dir, save_paths):
        if not _file_in_window(path, window_start, now, False):
            continue
        try:
            rel = _safe_rel(path, base_dir).as_posix()
            write_text(f"project/{rel}", path.read_text(encoding="utf-8", errors="replace"))
        except Exception as exc:
            unavailable.append(f"{path}: {exc}")

    included = files_count > 0
    reason = "; ".join(unavailable) if unavailable else None
    return {
        "files_count": files_count,
        "total_bytes": total_bytes,
        "included": included,
        "unavailable_reason": reason,
        "nginx_logs_included": nginx_success,
        "journal_logs_included": journal_success,
        "redacted_files": redacted,
    }


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


def create_debug_export_zip(
    *,
    base_dir: str | Path = ".",
    save_paths: dict | None = None,
    hours: int = 24,
    now: datetime | None = None,
    max_files: int = 50000,   # B142: 24h-Fenster ist die Grenze, nicht die Dateianzahl
    max_total_bytes: int | None = None,   # B140: Byte-Hartgrenze entfernt (None = unbegrenzt)
    tmp_path: str | Path | None = None,
) -> tuple[Path, str, dict]:
    base_dir = Path(base_dir).resolve()
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    window_start = now - timedelta(hours=hours)
    stamp = now.strftime("%Y-%m-%d_%H-%M-%S")
    root_name = f"wetterextended_debug_{stamp}_last{hours}h"
    filename = f"{root_name}.zip"
    if tmp_path is None:
        tmp = tempfile.NamedTemporaryFile(prefix="wetterextended_debug_", suffix=".zip", delete=False)
        tmp_path = Path(tmp.name)
        tmp.close()
    else:
        tmp_path = Path(tmp_path)

    started = time.perf_counter()
    candidates, diagnostics = _build_candidates_with_diagnostics(base_dir, save_paths)
    included_roots: set[str] = set()
    excluded_files: list[str] = []
    redacted_files: list[str] = []
    files_by_section: dict[str, int] = {}
    total_bytes = 0
    total_files = 0
    external_sources: set[str] = set()
    skipped_old_files = 0

    try:
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
                    skipped_old_files += 1
                    continue
                if max_files and total_files + 1 > max_files:
                    raise ExportLimitExceeded(f"Debug-Export abgebrochen: max_files={max_files} überschritten")
                section = cand.section
                arcname = f"{root_name}/{cand.arc_rel.as_posix()}"
                try:
                    if _is_text_file(path):
                        data = _read_redacted(path)
                        next_size = len(data)
                        # B140: keine Byte-Gesamtgrenze mehr (Volume-Split via B128).
                        zf.writestr(arcname, data)
                        total_bytes += next_size
                        redacted_files.append(rel)
                    else:
                        next_size = path.stat().st_size
                        # B140: keine Byte-Gesamtgrenze mehr (Volume-Split via B128).
                        zf.write(path, arcname)
                        total_bytes += next_size
                    total_files += 1
                    files_by_section[section] = files_by_section.get(section, 0) + 1
                    included_roots.add(str(cand.arc_rel.parts[0]) if cand.arc_rel.parts else section)
                    if "external_responses" in cand.arc_rel.parts:
                        idx = cand.arc_rel.parts.index("external_responses")
                        if len(cand.arc_rel.parts) > idx + 1:
                            external_sources.add(cand.arc_rel.parts[idx + 1])
                except ExportLimitExceeded:
                    raise
                except Exception as exc:
                    excluded_files.append(f"{rel}: {exc}")

            api_log_info = _write_api_logs_to_zip(zf, root_name, base_dir, save_paths, window_start, now)
            if api_log_info["files_count"]:
                total_files += api_log_info["files_count"]
                total_bytes += api_log_info["total_bytes"]
                files_by_section["api_logs"] = files_by_section.get("api_logs", 0) + api_log_info["files_count"]
                included_roots.add("api_logs")
                redacted_files.extend(api_log_info["redacted_files"])

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
                "api_logs_files_count": api_log_info["files_count"],
                "api_logs_included": api_log_info["included"],
                "api_logs_unavailable_reason": api_log_info["unavailable_reason"],
                "nginx_logs_included": api_log_info["nginx_logs_included"],
                "duration_s": round(time.perf_counter() - started, 3),
                "candidates_count": diagnostics["candidates_count"] + api_log_info["files_count"],
                "scanned_roots": diagnostics["scanned_roots"],
                "skipped_old_files": skipped_old_files,
                "excluded_files_count": diagnostics["excluded_files_count"] + len(excluded_files),
                "max_files": max_files,
                "max_total_bytes": max_total_bytes,
            }
            manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
            zf.writestr(f"{root_name}/manifest.json", manifest_bytes)
        manifest["total_files"] = total_files
        return tmp_path, filename, manifest
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

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
