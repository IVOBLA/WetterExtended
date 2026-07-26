#!/usr/bin/env python3
"""B465 — Einziger erlaubter Shell-Zugang der lokalen Analyse (streng lesend)."""
from __future__ import annotations
import argparse
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ALLOWED_UNITS = (
    "wetterprojekt.service", "wetterprojekt-scheduler.service",
    "wetterprojekt-admin.service", "wetterprojekt-local-analysis.service",
    "wetterprojekt-local-analysis.timer",
    "wetterprojekt-debug-export-branch.service",
    "wetterprojekt-debug-export-branch.timer",
)
ALLOWED_PRIORITIES = ("emerg", "alert", "crit", "err", "warning", "notice", "info")
MAX_JOURNAL_LINES = 200
MAX_HOURS = 168
MAX_ROWS = 200
SQL_START = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
SQL_FORBIDDEN = re.compile(
    r"\b(attach|detach|pragma|insert|update|delete|drop|create|alter|replace|"
    r"vacuum|reindex|begin|commit|rollback)\b", re.IGNORECASE,
)

class QueryError(ValueError):
    """Ungueltige Anfrage (Exit-Code 1)."""

def is_secret_name(name: str) -> bool:
    """B469 — Erkennt Zugangsdaten inklusive Sicherungskopien.

    Der bisherige Test name == ".env" or startswith(".env.") liess Kopien wie
    .env_Copy, .env.bak oder .env~ durch. Diese eine Funktion deckt jede
    .env-Variante ab, dazu Schluessel-/Zertifikatsdateien und SSH-Schluessel.
    """
    low = name.lower()
    if low.startswith(".env"):
        return True
    if low.endswith((".pem", ".key")):
        return True
    if "id_rsa" in low:
        return True
    return False

def check_unit(name: str) -> str:
    if name not in ALLOWED_UNITS:
        raise QueryError(f"Unit nicht erlaubt: {name!r}. Erlaubt: {', '.join(ALLOWED_UNITS)}")
    return name

def check_hours(value) -> int:
    try:
        hours = int(value)
    except (TypeError, ValueError):
        raise QueryError(f"Stunden muessen eine Zahl sein: {value!r}")
    if not 1 <= hours <= MAX_HOURS:
        raise QueryError(f"Stunden muessen zwischen 1 und {MAX_HOURS} liegen")
    return hours

def check_priority(value: str) -> str:
    if value not in ALLOWED_PRIORITIES:
        raise QueryError(f"Prioritaet nicht erlaubt: {value!r}. Erlaubt: {', '.join(ALLOWED_PRIORITIES)}")
    return value

def check_inside_repo(rel: str) -> Path:
    """Loest einen relativen Pfad auf und stellt sicher, dass er im Projekt liegt."""
    if not rel or rel.startswith("/"):
        raise QueryError("Pfad muss relativ zum Projektverzeichnis sein")
    target = (REPO / rel).resolve()
    try:
        target.relative_to(REPO)
    except ValueError:
        raise QueryError(f"Pfad liegt ausserhalb des Projekts: {rel}")
    if is_secret_name(target.name):
        raise QueryError(f"Datei sieht nach Zugangsdaten aus und ist gesperrt: {target.name}")
    return target

def check_sql(sql: str) -> str:
    if ";" in sql:
        raise QueryError("Semikolon nicht erlaubt — genau eine Abfrage")
    if not SQL_START.match(sql):
        raise QueryError("Nur SELECT- oder WITH-Abfragen sind erlaubt")
    found = SQL_FORBIDDEN.search(sql)
    if found:
        raise QueryError(f"Schluesselwort nicht erlaubt: {found.group(0)}")
    return sql

def _run(argv: list) -> str:
    proc = subprocess.run(argv, shell=False, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=60)
    if proc.returncode != 0 and not proc.stdout:
        raise RuntimeError(f"{argv[0]} rc={proc.returncode}: {(proc.stderr or '').strip()[:300]}")
    return proc.stdout

def cmd_services(_args) -> str:
    lines = []
    for unit in ALLOWED_UNITS:
        proc = subprocess.run(["systemctl", "is-active", unit], shell=False,
                              stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, timeout=30)
        lines.append(f"{unit}: {(proc.stdout or proc.stderr).strip() or 'unbekannt'}")
    return "\n".join(lines)

def cmd_journal(args) -> str:
    unit, hours, prio = check_unit(args.unit), check_hours(args.hours), check_priority(args.priority)
    return _run(["journalctl", "--no-pager", "-u", unit, "--since",
                 f"{hours} hours ago", "-p", prio, "-n", str(MAX_JOURNAL_LINES)])

def _connect_readonly(path: Path) -> sqlite3.Connection:
    """Read-only Verbindung ueber den Python-Treiber — keine Shell, keine Punktbefehle."""
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)

def cmd_sqlite_check(args) -> str:
    path = check_inside_repo(args.path)
    if not path.is_file(): raise QueryError(f"Datei nicht gefunden: {args.path}")
    con = _connect_readonly(path)
    try: rows = con.execute("PRAGMA quick_check").fetchall()
    finally: con.close()
    return f"{args.path}: " + "; ".join(str(r[0]) for r in rows)

def cmd_sqlite_tables(args) -> str:
    path = check_inside_repo(args.path)
    if not path.is_file(): raise QueryError(f"Datei nicht gefunden: {args.path}")
    con, out = _connect_readonly(path), []
    try:
        names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        for name in names:
            if not re.fullmatch(r"[A-Za-z0-9_]+", name): continue
            count = con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            out.append(f"{name}: {count} Zeilen")
    finally: con.close()
    return "\n".join(out) or "(keine Tabellen)"

def cmd_sqlite_select(args) -> str:
    path = check_inside_repo(args.path)
    if not path.is_file(): raise QueryError(f"Datei nicht gefunden: {args.path}")
    sql, con = check_sql(args.sql), _connect_readonly(path)
    try:
        cur = con.execute(sql); head = [d[0] for d in (cur.description or [])]; rows = cur.fetchmany(MAX_ROWS)
    finally: con.close()
    lines = [" | ".join(head)] if head else []
    lines += [" | ".join("" if v is None else str(v) for v in row) for row in rows]
    if len(rows) == MAX_ROWS: lines.append(f"... (bei {MAX_ROWS} Zeilen abgeschnitten)")
    return "\n".join(lines) or "(keine Zeilen)"

def cmd_files(args) -> str:
    pattern = args.pattern
    if ".." in pattern or pattern.startswith("/"): raise QueryError("Muster muss relativ und ohne '..' sein")
    now, out = time.time(), []
    for path in sorted(REPO.glob(pattern)):
        if not path.is_file(): continue
        try: path.relative_to(REPO)
        except ValueError: continue
        if is_secret_name(path.name): continue
        st = path.stat(); age_h = (now - st.st_mtime) / 3600
        out.append(f"{path.relative_to(REPO)}: {st.st_size} Bytes, Alter {age_h:.1f} h")
        if len(out) >= MAX_ROWS:
            out.append(f"... (bei {MAX_ROWS} Eintraegen abgeschnitten)"); break
    return "\n".join(out) or "(keine Treffer)"

def cmd_disk(_args) -> str:
    import shutil as _sh
    total, used, free = _sh.disk_usage(str(REPO)); pct = used / total * 100 if total else 0
    return f"Datentraeger {REPO}: gesamt {total // 2**20} MiB, belegt {used // 2**20} MiB ({pct:.1f} %), frei {free // 2**20} MiB"

def cmd_memory(_args) -> str:
    wanted = ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree")
    return "\n".join(line.strip() for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines() if line.split(":", 1)[0] in wanted)

def cmd_uptime(_args) -> str:
    up = float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0]); load = Path("/proc/loadavg").read_text(encoding="utf-8").split()[:3]
    return f"Uptime {up / 3600:.1f} h, Load {' '.join(load)}"

COMMANDS = {"services": cmd_services, "journal": cmd_journal, "sqlite-check": cmd_sqlite_check,
            "sqlite-tables": cmd_sqlite_tables, "sqlite-select": cmd_sqlite_select,
            "files": cmd_files, "disk": cmd_disk, "memory": cmd_memory, "uptime": cmd_uptime}

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ro_query.py", description="Streng lesende Abfragen fuer die lokale Analyse.")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("services", help="systemctl is-active fuer alle Projekt-Units")
    p = sub.add_parser("journal", help="Journal einer Projekt-Unit"); p.add_argument("unit"); p.add_argument("--hours", default=24); p.add_argument("--priority", default="err")
    p = sub.add_parser("sqlite-check", help="PRAGMA quick_check (read-only)"); p.add_argument("path")
    p = sub.add_parser("sqlite-tables", help="Tabellen und Zeilenzahlen"); p.add_argument("path")
    p = sub.add_parser("sqlite-select", help="eine einzelne SELECT-Abfrage"); p.add_argument("path"); p.add_argument("sql")
    p = sub.add_parser("files", help="Dateien mit Groesse und Alter"); p.add_argument("pattern")
    sub.add_parser("disk"); sub.add_parser("memory"); sub.add_parser("uptime")
    return ap

def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try: print(COMMANDS[args.command](args))
    except QueryError as exc:
        print(f"UNGUELTIG: {exc}", file=sys.stderr); return 1
    except Exception as exc:
        print(f"FEHLER: {exc}", file=sys.stderr); return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
