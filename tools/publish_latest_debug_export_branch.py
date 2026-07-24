#!/usr/bin/env python3
"""Veröffentlicht den neuesten WetterExtended-Debug-Export in einem eigenen Git-Branch.

Das produktive Repository wird nur gelesen. Der zu pushende Single-Commit-Branch
wird ausschließlich in einem temporären Git-Repository erzeugt.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

DEFAULT_BRANCH = "debug-export-latest"
DEFAULT_TARGET_PATH = "debug_exports/wetterextended_debug_latest_last24h.zip"
DEFAULT_HOURS = 24
DEFAULT_MAX_SOURCE_TOTAL_MB = 512
DEFAULT_MAX_ZIP_MB = 90
LOG_PREFIX = "[DEBUG-EXPORT-BRANCH]"
LOCK_PATH = Path("/tmp/wetterextended_debug_export_branch.lock")
EXPORT_REASON_SCHEDULED = "scheduled_branch_publish"
FORBIDDEN_BRANCHES = {"main", "master"}


class PublisherError(RuntimeError):
    """Verständlicher Abbruchfehler für CLI-Ausgaben."""


def log(message: str) -> None:
    print(f"{LOG_PREFIX} {message}", flush=True)


def fail(message: str) -> None:
    raise PublisherError(message)


def run_git(args: list[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = ["git", *args]
    result = subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True)
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        fail(f"Git-Befehl fehlgeschlagen: {' '.join(cmd)}\n{detail}")
    return result


def validate_branch(branch: str) -> str:
    branch = (branch or "").strip()
    if not branch:
        fail("Branch darf nicht leer sein.")
    if branch in FORBIDDEN_BRANCHES or branch.startswith("refs/heads/main"):
        fail(f"Sicherheitsabbruch: Branch '{branch}' darf nicht als Export-Ziel verwendet werden.")
    if branch.startswith("-") or ".." in branch or branch.endswith(".") or "@{" in branch or " " in branch:
        fail(f"Ungültiger Branchname: {branch}")
    return branch


def validate_relative_path(path_value: str) -> PurePosixPath:
    if not path_value:
        fail("Zielpfad darf nicht leer sein.")
    if "\\" in path_value:
        fail("Zielpfad muss POSIX-Trennzeichen '/' verwenden.")
    raw_parts = path_value.split("/")
    if any(part in {"", ".", "..", ".git"} for part in raw_parts):
        fail(f"Unsicherer Zielpfad: {path_value}")
    path = PurePosixPath(path_value)
    if path.is_absolute():
        fail(f"Zielpfad muss relativ sein: {path_value}")
    if path.suffix.lower() != ".zip":
        fail(f"Zielpfad muss auf .zip enden: {path_value}")
    for part in path.parts:
        if part in {"", ".", "..", ".git"}:
            fail(f"Unsicherer Zielpfadbestandteil '{part}' in: {path_value}")
    return path


def env_default(name: str, fallback: str | int) -> str:
    return os.environ.get(name, str(fallback))


def env_int(name: str) -> int | None:
    value = os.environ.get(name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError as exc:
        fail(f"Environment-Variable {name} muss eine ganze Zahl sein: {value}")
        raise exc


def resolve_max_source_total_mb(args: argparse.Namespace) -> int:
    if args.max_source_total_mb is not None:
        return args.max_source_total_mb
    env_source_total_mb = env_int("WETTER_DEBUG_EXPORT_MAX_SOURCE_TOTAL_MB")
    if env_source_total_mb is not None:
        return env_source_total_mb
    if args.max_total_mb is not None:
        return args.max_total_mb
    env_legacy_total_mb = env_int("WETTER_DEBUG_EXPORT_MAX_TOTAL_MB")
    if env_legacy_total_mb is not None:
        return env_legacy_total_mb
    return DEFAULT_MAX_SOURCE_TOTAL_MB


def resolve_max_zip_mb(args: argparse.Namespace) -> int:
    if args.max_zip_mb is not None:
        return args.max_zip_mb
    env_zip_mb = env_int("WETTER_DEBUG_EXPORT_MAX_ZIP_MB")
    if env_zip_mb is not None:
        return env_zip_mb
    return DEFAULT_MAX_ZIP_MB


def format_mb(byte_count: int) -> str:
    return f"{byte_count / 1024 / 1024:.1f}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-dir", default=env_default("WETTER_REPO_DIR", "."))
    parser.add_argument("--branch", default=env_default("WETTER_DEBUG_EXPORT_BRANCH", DEFAULT_BRANCH))
    parser.add_argument("--target-path", default=env_default("WETTER_DEBUG_EXPORT_TARGET_PATH", DEFAULT_TARGET_PATH))
    parser.add_argument("--hours", type=int, default=int(env_default("WETTER_DEBUG_EXPORT_HOURS", DEFAULT_HOURS)))
    parser.add_argument("--max-source-total-mb", type=int, default=None, help="Maximale unkomprimierte Exportdaten vor ZIP-Kompression in MB.")
    parser.add_argument("--max-zip-mb", type=int, default=None, help="Maximale finale ZIP-Dateigröße für GitHub in MB.")
    parser.add_argument("--max-total-mb", type=int, default=None, help="DEPRECATED: Legacy-Alias für --max-source-total-mb.")
    parser.add_argument("--check-only", action="store_true", help="Nur GitHub-Schreibrecht per git push --dry-run prüfen.")
    parser.add_argument("--dry-run", action="store_true", help="Export und temporären Commit erzeugen, aber nicht pushen.")
    args = parser.parse_args(argv)
    args.branch = validate_branch(args.branch)
    args.target_path = validate_relative_path(args.target_path)
    if args.hours <= 0:
        fail("--hours muss größer als 0 sein.")
    args.max_source_total_mb = resolve_max_source_total_mb(args)
    args.max_zip_mb = resolve_max_zip_mb(args)
    if args.max_source_total_mb <= 0:
        fail("--max-source-total-mb muss größer als 0 sein.")
    if args.max_zip_mb <= 0:
        fail("--max-zip-mb muss größer als 0 sein.")
    args.repo_dir = Path(args.repo_dir).resolve()
    return args


@contextmanager
def exclusive_lock():
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("w", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            fail("Ein anderer Debug-Export-Branch-Lauf ist bereits aktiv.")
            raise exc
        yield


def ensure_repo(repo_dir: Path) -> None:
    if not repo_dir.exists():
        fail(f"Repo-Verzeichnis existiert nicht: {repo_dir}")
    if not (repo_dir / ".git").exists():
        fail(f"Kein Git-Checkout gefunden: {repo_dir} ('.git' fehlt).")
    run_git(["rev-parse", "--is-inside-work-tree"], cwd=repo_dir)
    if not run_git(["remote", "get-url", "origin"], cwd=repo_dir, check=False).stdout.strip():
        fail("Git-Remote 'origin' fehlt. Für automatischen GitHub-Export ist ein origin-Remote nötig.")


def git_commit(repo_dir: Path) -> str:
    return run_git(["rev-parse", "HEAD"], cwd=repo_dir).stdout.strip()


def check_write_access(repo_dir: Path, branch: str) -> None:
    head = git_commit(repo_dir)
    refspec = f"{head}:refs/heads/{branch}"
    log(f"Prüfe GitHub-Schreibrecht: git push --dry-run --force origin {head[:12]}:refs/heads/{branch}")
    result = run_git(["push", "--dry-run", "--force", "origin", refspec], cwd=repo_dir, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        fail(
            "GitHub-Schreibtest fehlgeschlagen. Bitte SSH Deploy Key oder PAT mit Write-Zugriff einrichten.\n"
            f"Details:\n{detail}"
        )
    log("GitHub-Schreibtest erfolgreich.")


def _export_base_dir(repo_dir: Path) -> Path:
    """Basisverzeichnis für latest_export/ — identisch zur Auflösung in app.py.

    app.py bevorzugt WETTEREXTENDED_EXPORT_BASE_DIR und fällt sonst auf das
    Projektverzeichnis zurück; app.config["DEBUG_EXPORT_BASE_DIR"] existiert nur in
    Tests. Weicht das Tool hiervon ab, schreibt es an einen Ort, den die Route
    /api/admin/export/latest/meta nicht liest — der Fix wäre wirkungslos.
    """
    env_base = os.environ.get("WETTEREXTENDED_EXPORT_BASE_DIR")
    return Path(env_base or repo_dir).expanduser().resolve()


def persist_for_admin_panel(parts: "list[tuple[Path, str]]", manifest: dict, repo_dir: Path) -> dict | None:
    """B429: Legt den automatisch erstellten Export dort ab, wo ihn das Admin-Panel findet.

    Wird vor dem Push aufgerufen: der lokale Download soll auch dann existieren, wenn
    GitHub nicht erreichbar ist oder ein Volume das Push-Limit überschreitet. Ein
    Fehler hier darf den Push nicht verhindern — der Branch bleibt der Zweitweg.
    """
    sys.path.insert(0, str(repo_dir))
    from config import SAVE_PATHS  # pylint: disable=import-outside-toplevel
    from debug_export import persist_latest_export  # pylint: disable=import-outside-toplevel

    try:
        meta = persist_latest_export(parts, manifest, save_paths=SAVE_PATHS, base_dir=_export_base_dir(repo_dir))
        log(f"Für Admin-Panel persistiert: {meta.get('part_count')} Teil(e), "
            f"{format_mb(meta.get('total_bytes') or 0)} MB, Grund '{meta.get('export_reason')}'.")
        return meta
    except Exception as exc:  # pylint: disable=broad-except
        log(f"WARNUNG: Persistenz für das Admin-Panel fehlgeschlagen ({exc}). "
            "Der Push in den Branch wird trotzdem versucht.")
        return None


def create_export(repo_dir: Path, hours: int, max_source_total_mb: int, max_zip_mb: int) -> tuple[list[tuple[Path, str]], dict]:
    sys.path.insert(0, str(repo_dir))
    from config import SAVE_PATHS  # pylint: disable=import-outside-toplevel
    from debug_export import create_debug_export_volumes, persist_latest_export  # pylint: disable=import-outside-toplevel

    volume_max_bytes = max_zip_mb * 1024 * 1024
    log(
        f"Erzeuge Debug-Volumes der letzten {hours} Stunden "
        f"(Volume-Limit: {max_zip_mb} MB, keine Auslassung)."
    )
    parts, manifest = create_debug_export_volumes(
        base_dir=repo_dir,
        save_paths=SAVE_PATHS,
        hours=hours,
        volume_max_bytes=volume_max_bytes,
    )
    # B429: Herkunft kennzeichnen. create_debug_export_volumes setzt für jeden Pfad
    # "last_24h_debug_run"; ohne diese Unterscheidung ist im Admin-Panel nicht
    # erkennbar, ob der angebotene Export vom Timer oder vom Button stammt.
    manifest = {**manifest, "export_reason": EXPORT_REASON_SCHEDULED}
    return parts, manifest


def write_branch_repo(
    *,
    temp_repo: Path,
    source_zip: list[tuple[Path, str]],
    source_filename: str,
    export_manifest: dict,
    repo_dir: Path,
    branch: str,
    target_path: PurePosixPath,
    hours: int,
    max_source_total_mb: int,
    max_zip_mb: int,
    zip_size_bytes: int,
) -> dict:
    run_git(["init", "-b", branch], cwd=temp_repo)
    run_git(["config", "user.name", "WetterExtended Debug Export"], cwd=temp_repo)
    run_git(["config", "user.email", "debug-export@wetterextended.local"], cwd=temp_repo)
    remote = run_git(["remote", "get-url", "origin"], cwd=repo_dir).stdout.strip()
    run_git(["remote", "add", "origin", remote], cwd=temp_repo)

    # B126: source_zip ist jetzt eine Liste [(Path, name), …] — alle Teile ablegen.
    dst_dir = temp_repo / Path(*target_path.parts).parent
    dst_dir.mkdir(parents=True, exist_ok=True)
    part_names = []
    for _p, _name in source_zip:
        shutil.copy2(_p, dst_dir / _name)
        part_names.append((Path(*target_path.parts).parent / _name).as_posix())

    manifest = {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "branch": branch,
        "target_path": target_path.as_posix(),
        "source_zip_filename": source_filename,
        "part_files": part_names,
        "source_commit": git_commit(repo_dir),
        "hours": hours,
        "max_source_total_mb": max_source_total_mb,
        "max_zip_mb": max_zip_mb,
        "zip_size_bytes": zip_size_bytes,
        "export_manifest": export_manifest,
    }
    manifest_path = temp_repo / "debug_exports" / "latest_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    (temp_repo / "README.md").write_text(
        "# WetterExtended Debug-Export\n\n"
        "Dieser Branch wird automatisch erzeugt und per Force-Push ersetzt.\n\n"
        f"Aktueller Export-Ordner: `{Path(*target_path.parts).parent.as_posix()}/`\n\n"
        f"Teile: {', '.join(f'`{name}`' for name in part_names)}\n\n"
        "Der produktive `main`-Branch bleibt unverändert; dieser Branch enthält nur den letzten Debug-Export.\n",
        encoding="utf-8",
    )

    eval_src = repo_dir / "train_data" / "evaluation"
    eval_dst = temp_repo / "evaluation"
    eval_dst.mkdir(parents=True, exist_ok=True)
    for diag_name in ("forecast_quality_diagnosis_latest.json", "forecast_quality_diagnosis_error.json"):
        src = eval_src / diag_name
        if src.exists():
            shutil.copy2(src, eval_dst / diag_name)
    run_git(["add", "README.md", "debug_exports", "evaluation"], cwd=temp_repo)
    run_git(["commit", "-m", "chore(debug-export): publish latest last24h ZIP"], cwd=temp_repo)
    return manifest


def analysis_mode(repo_dir: Path) -> str:
    """Betriebsart der taeglichen Analyse: "repo" oder "local" (P82).

    Wird nur gelesen. Faellt bei jedem Problem auf "repo" zurueck, damit ein
    defektes runtime_overrides.json niemals den Export-Push verhindert.
    """
    try:
        repo_dir = Path(repo_dir).resolve()
        if str(repo_dir) not in sys.path:
            sys.path.insert(0, str(repo_dir))
        from config import ANALYSIS_MODE as _default
        try:
            import runtime_config

            runtime_config.reload_overrides()
            value = runtime_config.get("ANALYSIS_MODE", _default)
        except Exception:
            value = _default
        return str(value or "repo").strip().lower()
    except Exception as exc:
        log(f"Betriebsart nicht ermittelbar ({exc}) — nehme 'repo' an.")
        return "repo"


def publish(args: argparse.Namespace) -> None:
    ensure_repo(args.repo_dir)
    if args.check_only:
        check_write_access(args.repo_dir, args.branch)
        return

    parts: list[tuple[Path, str]] = []
    try:
        with tempfile.TemporaryDirectory(prefix="wetterextended_debug_branch_") as tmpdir:
            tmp_repo = Path(tmpdir)
            parts, export_manifest = create_export(
                args.repo_dir, args.hours, args.max_source_total_mb, args.max_zip_mb
            )
            zip_size_bytes = sum(path.stat().st_size for path, _name in parts)
            filename = parts[0][1] if len(parts) == 1 else f"{Path(*args.target_path.parts).stem}_parts.zip"
            log(f"Debug-Volumes erstellt: {len(parts)} Teile ({format_mb(zip_size_bytes)} MB gesamt).")
            # B429: zuerst lokal für das Admin-Panel ablegen, dann pushen. Der finally-
            # Block löscht die Quell-Volumes; ohne diese Kopie wäre der automatische
            # Export nirgends herunterladbar. Reihenfolge ist bindend: der Push darf
            # scheitern, der Download muss trotzdem existieren.
            if args.dry_run:
                log("Dry-run: keine Persistenz für das Admin-Panel.")
            else:
                persist_for_admin_panel(parts, export_manifest, args.repo_dir)
                # P82: In der Betriebsart "local" analysiert der Pi selbst. Der
                # Branch wird dann von niemandem gelesen — der Push entfaellt.
                # Der Admin-Panel-Download ist oben bereits abgelegt und bleibt
                # vollstaendig erhalten. Reihenfolge ist bindend.
                if analysis_mode(args.repo_dir) == "local":
                    log(
                        "Betriebsart 'local': kein Push nach GitHub "
                        "(die Analyse laeuft am Pi). Admin-Panel-Export wurde abgelegt."
                    )
                    return
            max_zip_bytes = args.max_zip_mb * 1024 * 1024
            oversized = [(path, name) for path, name in parts if path.stat().st_size > max_zip_bytes]
            if oversized:
                details = ", ".join(f"{name}={format_mb(path.stat().st_size)} MB" for path, name in oversized)
                # B141: GitHub kann Dateien > Limit (~100 MB) nicht pushen → klar abbrechen
                # statt später am git push zu scheitern. Der Admin-Download bleibt verlustfrei
                # (create_debug_export_volumes); nur der Publisher lehnt Übergrößen-Volumes ab.
                raise PublisherError(
                    f"Finale ZIP-Datei ist zu groß für GitHub (Limit {args.max_zip_mb} MB): {details}. "
                    "Ursache meist eine einzelne Datei > Limit — bitte Daten-Rotation/Retention prüfen."
                )
            manifest = write_branch_repo(
                temp_repo=tmp_repo,
                source_zip=parts,
                source_filename=filename,
                export_manifest=export_manifest,
                repo_dir=args.repo_dir,
                branch=args.branch,
                target_path=args.target_path,
                hours=args.hours,
                max_source_total_mb=args.max_source_total_mb,
                max_zip_mb=args.max_zip_mb,
                zip_size_bytes=zip_size_bytes,
            )
            if args.dry_run:
                log(f"Dry-run: kein Push. Temporärer Commit für {manifest['target_path']} wurde erfolgreich erzeugt.")
                return
            refspec = f"HEAD:refs/heads/{args.branch}"
            log(f"Pushe Export-Branch per Force-Push: {args.branch}")
            run_git(["push", "--force", "origin", refspec], cwd=tmp_repo)
            log(f"Export veröffentlicht: {args.branch}/{args.target_path.as_posix()}")
    finally:
        for path, _name in parts:
            path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        if args.check_only:
            publish(args)
        else:
            with exclusive_lock():
                publish(args)
        return 0
    except PublisherError as exc:
        print(f"{LOG_PREFIX} FEHLER: {exc}", file=sys.stderr, flush=True)
        return 1
    except Exception as exc:  # robuste CLI-Meldung für systemd/journalctl
        print(f"{LOG_PREFIX} FEHLER: Unerwarteter Fehler: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
