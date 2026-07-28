#!/usr/bin/env python3
"""P83 — Deterministischer AIChecks-Runner.

Arbeitet ALLE ACs aus AIChecks.md ('## Offen') bei jedem Lauf vollstaendig ab —
unabhaengig vom LLM-Schrittbudget — und schreibt ein maschinenlesbares Ergebnis.
Nicht migrierte ACs erscheinen als 'not_implemented'; dafuer greift weiterhin der
LLM-Fallback im lokalen Analyse-Prompt.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=str(_repo_root()),
                    help="Datenwurzel (enthaelt train_data/...). Default: Repo-Wurzel.")
    ap.add_argument("--aichecks", default=None,
                    help="Pfad zu AIChecks.md. Default: <repo>/AIChecks.md")
    ap.add_argument("--out", default=None,
                    help="Ausgabedatei. Default: <base>/train_data/evaluation/ai_checks_results.json")
    args = ap.parse_args(argv)

    if str(_repo_root()) not in sys.path:
        sys.path.insert(0, str(_repo_root()))
    from tools.ai_checks import run_all, parse_open_acs  # noqa: F401

    base = Path(args.base).resolve()
    aichecks = Path(args.aichecks) if args.aichecks else _repo_root() / "AIChecks.md"
    out = Path(args.out) if args.out else base / "train_data/evaluation/ai_checks_results.json"

    summary = run_all(base, aichecks)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(out))
    print(f"[AI-CHECKS] {summary['total_acs']} ACs "
          f"({summary['implemented']} implementiert, {summary['not_implemented']} offen), "
          f"{summary['findings']} Befunde, {summary['errors']} Fehler → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
