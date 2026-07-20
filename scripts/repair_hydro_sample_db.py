#!/usr/bin/env python3
"""B432: Hydro-ML-Sample-Datenbank prüfen und bei Freigabe reparieren."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hydro_flood_ml  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Hydro-ML-Sample-DB prüfen und reparieren")
    parser.add_argument("--apply", action="store_true", help="Reparatur wirklich durchführen")
    args = parser.parse_args()
    integrity = hydro_flood_ml.sample_db_integrity()
    print(json.dumps(integrity, indent=2, ensure_ascii=False, default=str))
    if integrity.get("integrity_status") == "ok":
        print("\nDatenbank ist in Ordnung — keine Reparatur nötig.")
        return 0
    if integrity.get("integrity_status") == "missing":
        print("\nKeine Datenbank vorhanden.")
        return 0
    if not args.apply:
        print("\nDefekt erkannt. Reparatur mit --apply auslösen.")
        print("Vorher die schreibenden Dienste stoppen:")
        print("  sudo systemctl stop wetterprojekt-scheduler wetterprojekt-admin")
        return 1
    try:
        report = hydro_flood_ml.repair_sample_db()
    except BlockingIOError:
        print("\nFEHLER: Ein Trainingslauf hält den Lock. Später erneut versuchen.")
        return 2
    print("\n--- Reparaturbericht ---")
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    if report.get("repair_status") != "repaired":
        print(f"\nFEHLGESCHLAGEN: {report.get('repair_status')}")
        return 3
    print(f"\nOK: {report.get('rows_copied')} Zeilen gerettet, "
          f"{report.get('rows_skipped')} unlesbar übersprungen.")
    print(f"Original liegt in Quarantäne: {report.get('quarantine_path')}")
    print("Dienste wieder starten:")
    print("  sudo systemctl start wetterprojekt-scheduler wetterprojekt-admin")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
