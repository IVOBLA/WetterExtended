"""P83 — Deterministischer AIChecks-Harness (Registry + Runner-Kern).

Ziel: Alle in AIChecks.md ("## Offen") gelisteten ACs werden bei JEDEM Lauf
vollstaendig abgearbeitet — unabhaengig vom LLM-Schrittbudget. Jeder AC wird
entweder von einer registrierten, deterministischen Pruefung ausgewertet oder als
"not_implemented" markiert (dann greift weiterhin der LLM-Fallback im lokalen
Analyse-Prompt). Kein einzelner Check-Fehler darf den Gesamtlauf abbrechen.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

# Registry: AC-Id -> Prueffunktion. Signatur: fn(base: Path) -> dict mit den
# Schluesseln status/beleg/detail. status in VALID_STATUS.
CHECKS: Dict[str, Callable[[Path], dict]] = {}
VALID_STATUS = frozenset({"ok", "finding", "error", "not_implemented"})
_AC_HEADING = re.compile(r"^### (AC-\d+)\s+—\s+(.*?)\s*$")


def register(ac_id: str):
    """Registriert genau eine deterministische Pruefung fuer einen AC."""
    def deco(fn: Callable[[Path], dict]) -> Callable[[Path], dict]:
        if ac_id in CHECKS:
            raise ValueError(f"AC bereits registriert: {ac_id}")
        CHECKS[ac_id] = fn
        return fn
    return deco


def parse_open_acs(aichecks_path) -> List[Tuple[str, str]]:
    """Alle ACs (Id, Titel) aus dem Abschnitt '## Offen', in Dokumentreihenfolge."""
    text = Path(aichecks_path).read_text(encoding="utf-8")
    out: List[Tuple[str, str]] = []
    in_open = False
    for line in text.splitlines():
        if line.startswith("## "):
            in_open = (line.strip() == "## Offen")
            continue
        if in_open:
            m = _AC_HEADING.match(line)
            if m:
                out.append((m.group(1), m.group(2)))
    return out


def _load_default_checks() -> None:
    """Nebenwirkung: importiert die Check-Module, deren @register die Registry fuellt."""
    from importlib import import_module
    import_module("tools.ai_checks.checks_local")


def run_all(base, aichecks_path,
            checks: Optional[Dict[str, Callable[[Path], dict]]] = None) -> dict:
    """Wertet ALLE offenen ACs aus. Vollstaendig und abbruchsicher.

    checks=None -> Standard-Registry (laedt die Check-Module). Der Parameter
    dient der Testinjektion (Dependency Injection).
    """
    base = Path(base)
    if checks is None:
        _load_default_checks()
        checks = CHECKS
    acs = parse_open_acs(aichecks_path)
    results: List[dict] = []
    for ac_id, titel in acs:
        fn = checks.get(ac_id)
        if fn is None:
            results.append({"ac": ac_id, "titel": titel, "status": "not_implemented",
                            "beleg": "", "detail": {}})
            continue
        try:
            r = fn(base) or {}
            status = str(r.get("status", "error"))
            if status not in VALID_STATUS:
                status = "error"
            results.append({"ac": ac_id, "titel": titel, "status": status,
                            "beleg": str(r.get("beleg", "")), "detail": r.get("detail", {})})
        except Exception as exc:  # kein einzelner Check darf den Gesamtlauf stoppen
            results.append({"ac": ac_id, "titel": titel, "status": "error",
                            "beleg": f"{type(exc).__name__}: {exc}", "detail": {}})
    return {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "base_dir": str(base),
        "total_acs": len(acs),
        "implemented": sum(1 for r in results if r["status"] != "not_implemented"),
        "not_implemented": sum(1 for r in results if r["status"] == "not_implemented"),
        "findings": sum(1 for r in results if r["status"] == "finding"),
        "errors": sum(1 for r in results if r["status"] == "error"),
        "results": results,
    }
