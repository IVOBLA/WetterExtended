#!/usr/bin/env python3
"""Diagnose/Reparatur für current-Modelle mit nicht-promoted training_meta.json."""
import argparse
import json
import math
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import MIN_SEQUENCES_LSTM, SAVE_PATHS  # noqa: E402
from ml_readiness import ACTIVE_MODEL_STATUSES, check_ml_readiness, get_forecast_runtime_status  # noqa: E402

REQUIRED = 50


def clean(v):
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if isinstance(v, list):
        return [clean(x) for x in v]
    return v


def meta_path():
    return Path(SAVE_PATHS.get("models", "train_data/models")) / "current" / "training_meta.json"


def load_meta(path):
    if not path.exists():
        return {}
    return clean(json.loads(path.read_text(encoding="utf-8")))


def write_meta(path, meta):
    backup = path.with_suffix(path.suffix + ".bak_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"))
    if path.exists():
        shutil.copy2(path, backup)
    path.write_text(json.dumps(clean(meta), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return backup


def diagnose():
    rd = check_ml_readiness(write_json=False)
    rt = get_forecast_runtime_status(write_json=False)
    status = rd.get("promotion_status")
    action = "none"
    if rd.get("ml_artifacts_available") and status not in ACTIVE_MODEL_STATUSES:
        action = "promote-low-confidence (falls fachlich gewünscht) oder deactivate"
    return rd, rt, action


def ensure_dataset(meta):
    if not isinstance(meta.get("dataset"), dict):
        n = int(meta.get("num_samples", 0) or 0)
        meta["dataset"] = {"scope": "unknown", "retention_days": None, "total_samples": n, "train_samples": None, "holdout_samples": None, "sequence_length": None}


def promote_low_confidence(path, meta, rd):
    total = int(((meta.get("dataset") or {}).get("total_samples") or meta.get("num_samples") or rd.get("dataset_sequences") or 0))
    if not rd.get("ml_artifacts_available"):
        raise SystemExit("Abbruch: Artefakte sind nicht vollständig/ladefähig.")
    if total < int(MIN_SEQUENCES_LSTM):
        raise SystemExit(f"Abbruch: Dataset-Samples {total} < MIN_SEQUENCES_LSTM {MIN_SEQUENCES_LSTM}.")
    ensure_dataset(meta)
    val = meta.setdefault("validation", {})
    recent = int(val.get("samples_recent") or 0)
    meta["status"] = "cold_start_promoted_low_confidence"
    val.update({
        "status": "cold_start_promoted_low_confidence",
        "low_confidence": True,
        "samples_required": REQUIRED,
        "samples_missing": max(0, REQUIRED - recent),
        "status_reason": f"Erstes ML-Modell wurde als Low-Confidence-Modell aktiviert, obwohl erst {recent} von {REQUIRED} aktuellen Promotion-/Validierungs-Samples vorhanden sind.",
    })
    backup = write_meta(path, meta)
    print(f"promoted_low_confidence=yes backup={backup}")


def deactivate(path, meta):
    ensure_dataset(meta)
    status = ((meta.get("validation") or {}).get("status") or meta.get("status") or "missing_promotion_status")
    meta.setdefault("validation", {})["status_reason"] = f"Current bleibt vorhanden, wird aber nicht als ML aktiv akzeptiert: {status}"
    backup = write_meta(path, meta)
    print(f"deactivated=yes backup={backup}")


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--promote-low-confidence", action="store_true")
    g.add_argument("--deactivate", action="store_true")
    args = ap.parse_args()
    path = meta_path(); rd, rt, action = diagnose(); meta = load_meta(path)
    print(f"current target: {os.path.realpath(path.parent)}")
    print(f"artifact valid: {'yes' if rd.get('ml_artifacts_available') else 'no'}")
    print(f"promotion status: {rd.get('promotion_status')}")
    print(f"runtime decision: {rt.get('runtime_mode')}")
    print(f"fallback reason: {rt.get('fallback_reason')}")
    print(f"recommended action: {action}")
    if args.promote_low_confidence:
        promote_low_confidence(path, meta, rd)
    elif args.deactivate:
        deactivate(path, meta)

if __name__ == "__main__":
    main()
