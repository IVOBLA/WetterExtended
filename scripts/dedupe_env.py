#!/usr/bin/env python3
"""B398: .env-Dateien last-wins-sicher und ohne Secret-Ausgabe deduplizieren."""
from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

_ASSIGNMENT_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


def _active_key(line: str) -> str | None:
    stripped = line.lstrip()
    if not stripped or stripped.startswith("#"):
        return None
    match = _ASSIGNMENT_RE.match(line)
    if not match:
        return None
    return match.group(1)


def dedupe_env_file(path: str | Path) -> list[str]:
    """Remove duplicate active assignments while preserving last-wins semantics."""
    env_path = Path(path)
    if not env_path.exists():
        return []

    stat = env_path.stat()
    lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)

    positions: dict[str, list[int]] = {}
    for index, line in enumerate(lines):
        key = _active_key(line)
        if key is not None:
            positions.setdefault(key, []).append(index)

    duplicate_keys = sorted(key for key, indexes in positions.items() if len(indexes) > 1)
    if not duplicate_keys:
        return []

    remove_indexes = {
        index
        for indexes in positions.values()
        if len(indexes) > 1
        for index in indexes[:-1]
    }
    new_lines = [line for index, line in enumerate(lines) if index not in remove_indexes]

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{env_path.name}.",
        suffix=".tmp",
        dir=str(env_path.parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as tmp:
            tmp.writelines(new_lines)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.chmod(tmp_name, stat.st_mode & 0o7777)
        os.replace(tmp_name, env_path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise

    return duplicate_keys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("Usage: python scripts/dedupe_env.py /pfad/zur/.env", file=sys.stderr)
        return 2

    keys = dedupe_env_file(args[0])
    if keys:
        print(
            "[B398] .env-Duplikate bereinigt, effektiver letzter Wert erhalten: "
            + ", ".join(keys)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
