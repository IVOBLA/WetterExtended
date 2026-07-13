"""Zentrale Forecast-Qualitätsdiagnose vor 24h-Debug-Exporten.

Die Diagnose nutzt ausschließlich lokal vorhandene Dateien und blockiert den
Export nicht: bei Fehlern wird eine stabile Fehlerdatei geschrieben.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from config import SAVE_PATHS
except Exception:  # pragma: no cover
    SAVE_PATHS = {"evaluation": "train_data/evaluation"}

LATEST_NAME = "forecast_quality_diagnosis_latest.json"
ERROR_NAME = "forecast_quality_diagnosis_error.json"
# B349: separate Konstanten fuer die Beschleunigungs-Validierung (eigene Datei,
# eigenes Skript tools/diagnose_kinematic_acceleration.py).
KINEMATIC_ACCEL_LATEST_NAME = "kinematic_acceleration_validation_latest.json"
KINEMATIC_ACCEL_ERROR_NAME = "kinematic_acceleration_validation_error.json"


def utc_now_z() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def evaluation_dir(base_dir: str | Path | None = None, save_paths: dict | None = None) -> Path:
    paths = save_paths or SAVE_PATHS
    raw = Path(paths.get("evaluation", "train_data/evaluation"))
    if raw.is_absolute() or base_dir is None:
        return raw
    return Path(base_dir) / raw


def run_forecast_quality_diagnosis_before_export(*, hours: int = 24, base_dir: str | Path | None = None, save_paths: dict | None = None) -> dict:
    """Führt die zentrale Diagnose robust vor jedem 24h-Export aus.

    Fehler werden als evaluation/forecast_quality_diagnosis_error.json persistiert
    und nicht weitergeworfen, damit Exportpfade unverändert weiterlaufen.
    """
    base = Path(base_dir or ".").resolve()
    ev = evaluation_dir(base, save_paths)
    ev.mkdir(parents=True, exist_ok=True)
    latest = ev / LATEST_NAME
    error = ev / ERROR_NAME
    script = Path(__file__).resolve().parent / "tools" / "diagnose_forecast_quality.py"
    cmd = [sys.executable, str(script), "--hours", str(int(hours)), "--base-dir", str(base), "--evaluation-dir", str(ev)]
    try:
        proc = subprocess.run(cmd, cwd=str(base), text=True, capture_output=True, timeout=int(os.getenv("FORECAST_QUALITY_DIAGNOSIS_TIMEOUT_S", "45")), check=False)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or f"diagnosis exited rc={proc.returncode}").strip())
        error.unlink(missing_ok=True)
        return {"status": "ok", "path": str(latest), "stdout": proc.stdout[-2000:]}
    except Exception as exc:  # noqa: BLE001 - Export darf nicht blockieren.
        payload = {"status": "error", "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc(), "timestamp_utc": utc_now_z()}
        error.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        latest.unlink(missing_ok=True)
        return payload


def run_kinematic_acceleration_diagnosis_before_export(*, hours: int = 24, base_dir: str | Path | None = None, save_paths: dict | None = None) -> dict:
    """B349: Validiert die Beschleunigungs-Root-Cause-Hypothese (B307/B348) robust
    vor jedem 24h-Export. Analog run_forecast_quality_diagnosis_before_export():
    Fehler werden persistiert, nicht weitergeworfen -- der Export darf nicht
    blockiert werden.
    """
    base = Path(base_dir or ".").resolve()
    ev = evaluation_dir(base, save_paths)
    ev.mkdir(parents=True, exist_ok=True)
    latest = ev / KINEMATIC_ACCEL_LATEST_NAME
    error = ev / KINEMATIC_ACCEL_ERROR_NAME
    script = Path(__file__).resolve().parent / "tools" / "diagnose_kinematic_acceleration.py"
    cmd = [sys.executable, str(script), "--hours", str(int(hours)), "--base-dir", str(base), "--evaluation-dir", str(ev)]
    try:
        proc = subprocess.run(cmd, cwd=str(base), text=True, capture_output=True, timeout=int(os.getenv("KINEMATIC_ACCEL_DIAGNOSIS_TIMEOUT_S", "45")), check=False)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or f"diagnosis exited rc={proc.returncode}").strip())
        error.unlink(missing_ok=True)
        return {"status": "ok", "path": str(latest), "stdout": proc.stdout[-2000:]}
    except Exception as exc:  # noqa: BLE001 - Export darf nicht blockieren.
        payload = {"status": "error", "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc(), "timestamp_utc": utc_now_z()}
        error.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        latest.unlink(missing_ok=True)
        return payload


def load_latest_kinematic_acceleration_diagnosis(*, base_dir: str | Path | None = None, save_paths: dict | None = None) -> dict:
    ev = evaluation_dir(base_dir, save_paths)
    for name in (KINEMATIC_ACCEL_LATEST_NAME, KINEMATIC_ACCEL_ERROR_NAME):
        path = ev / name
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                data.setdefault("file", name)
                return data
            except Exception as exc:
                return {"status": "error", "error": str(exc), "file": name}
    return {"status": "missing", "file": None, "important_findings": [], "recommendations": ["Noch keine Beschleunigungs-Validierung ausgefuehrt (B348 muss zuerst Daten sammeln)."]}


def load_latest_forecast_quality_diagnosis(*, base_dir: str | Path | None = None, save_paths: dict | None = None) -> dict:
    ev = evaluation_dir(base_dir, save_paths)
    for name in (LATEST_NAME, ERROR_NAME):
        path = ev / name
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                data.setdefault("file", name)
                return data
            except Exception as exc:
                return {"status": "error", "error": str(exc), "file": name}
    return {"status": "missing", "file": None, "important_findings": [], "recommendations": ["Noch keine Forecast-Qualitätsdiagnose ausgeführt."]}
