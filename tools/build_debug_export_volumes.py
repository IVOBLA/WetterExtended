#!/usr/bin/env python3
"""
tools/build_debug_export_volumes.py

B162: Standalone-Runner für den Debug-Export-Volume-Build.

Läuft als EIGENER Prozess (vom Admin-Backend via subprocess.Popen gestartet),
damit der CPU-intensive Build (> 60 s) NICHT den Flask-Hauptthread des
Admin-Service blockiert und damit den systemd-Watchdog (WatchdogSec=60)
aushungert (sonst SIGABRT → 502).

Schreibt nach Erfolg <out_dir>/manifest.json:
    {"status": "ready",
     "parts": [{"index": 1, "filename": "...", "bytes": N}, ...],
     "manifest": {...}}
Bei Fehler <out_dir>/error.json:
    {"status": "error", "detail": "...", "traceback": "..."}
Die ZIP-Volumes liegen direkt in <out_dir>.
"""
import argparse
import json
import sys
import traceback
from pathlib import Path


def _main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--base-dir", required=True)
    parser.add_argument("--hours", type=int, default=24)
    args = parser.parse_args(argv)

    repo_dir = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo_dir))

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        from config import SAVE_PATHS
        from debug_export import create_debug_export_volumes

        parts, manifest = create_debug_export_volumes(
            base_dir=Path(args.base_dir),
            save_paths=SAVE_PATHS,
            hours=args.hours,
            out_dir=out_dir,
        )
        result = {
            "status": "ready",
            "parts": [
                {"index": i, "filename": name, "bytes": Path(path).stat().st_size}
                for i, (path, name) in enumerate(parts, start=1)
            ],
            "manifest": manifest,
        }
        (out_dir / "manifest.json").write_text(
            json.dumps(result, ensure_ascii=False), encoding="utf-8"
        )
        return 0
    except Exception as exc:  # noqa: BLE001 — bewusst breit; Fehler landet in error.json
        (out_dir / "error.json").write_text(
            json.dumps(
                {
                    "status": "error",
                    "detail": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(_main())
