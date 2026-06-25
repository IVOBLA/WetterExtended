"""Zentrale Feature-Schema-Kompatibilität für ML-Trainingsdaten."""
from __future__ import annotations

import glob
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any

try:
    from config import DATASET_SCHEMA_VERSION as DATASET_SCHEMA_VERSION
except Exception:
    DATASET_SCHEMA_VERSION = "v1"
TIME_FEATURES = ["hour_sin", "hour_cos", "month_sin", "month_cos"]


def _cfg(name: str, default: Any = None) -> Any:
    try:
        import runtime_config
        import config
        return runtime_config.get(name, getattr(config, name, default))
    except Exception:
        try:
            import config
            return getattr(config, name, default)
        except Exception:
            return default


def _stable_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def get_current_feature_schema() -> dict:
    """Erzeugt eine stabile Beschreibung des aktuell erwarteten ML-Feature-Schemas."""
    cell_features = list(_cfg("ML_CELL_FEATURES", []))
    station_features = list(_cfg("ML_STATION_FEATURES", []))
    feature_names = cell_features + station_features + TIME_FEATURES
    schema = {
        "schema_version": DATASET_SCHEMA_VERSION,
        "feature_names": feature_names,
        "station_feature_names": station_features,
        "cell_feature_names": cell_features,
        "horizons_min": [int(h) for h in list(_cfg("ML_FORECAST_HORIZONS_MIN", []))],
        "target_encoding": str(_cfg("ML_TARGET_ENCODING", "delta")),
        "sequence_length": int(_cfg("ML_SEQUENCE_LENGTH", 0) or 0),
        "num_features": int(_cfg("ML_NUM_FEATURES", len(feature_names)) or len(feature_names)),
        "flags": {
            "CLIM_FEATURES_ENABLED": bool(_cfg("CLIM_FEATURES_ENABLED", False)),
            "ir_features_active": any(str(f).startswith(("ir_", "bt_", "cloud_")) or "ir" in str(f).lower() for f in cell_features),
            "hydro_features_active": any("hydro" in str(f).lower() or str(f).startswith(("q_", "w_")) for f in feature_names),
            "nowcast_features_active": any("nowcast" in str(f).lower() or "geosphere" in str(f).lower() for f in feature_names),
            "dem_orography_features_active": any(tok in str(f).lower() for f in feature_names for tok in ("dem", "orograph", "terrain", "elevation", "slope", "valley")),
        },
    }
    canonical = {k: v for k, v in schema.items() if k != "feature_schema_hash"}
    schema["feature_schema_hash"] = "sha256:" + hashlib.sha256(_stable_json(canonical).encode("utf-8")).hexdigest()
    return schema


compute_feature_schema = get_current_feature_schema


def schema_metadata(source_object_file: str | None = None, source_weather_file: str | None = None) -> dict:
    schema = get_current_feature_schema()
    return {
        "feature_schema_hash": schema["feature_schema_hash"],
        "feature_schema_version": schema["schema_version"],
        "schema_version": schema["schema_version"],
        "feature_names": list(schema["feature_names"]),
        "feature_count": int(schema["num_features"]),
        "horizons_min": list(schema["horizons_min"]),
        "target_encoding": schema["target_encoding"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_object_file": source_object_file,
        "source_weather_file": source_weather_file,
    }


def attach_schema_metadata(payload: Any, source_object_file: str | None = None, source_weather_file: str | None = None) -> Any:
    """Hängt aktuellen Schema-Metadaten an neu erzeugte Trainingsquellen an."""
    meta = schema_metadata(source_object_file, source_weather_file)
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                item.update(meta)
        return payload
    if isinstance(payload, dict):
        payload.update(meta)
    return payload


def extract_source_schema(obj: Any, weather: Any = None) -> dict:
    """Liest Schema-Metadaten aus Objekt-/Wetter-Rohdateien, sofern vorhanden."""
    candidates = []
    for payload in (obj, weather):
        if isinstance(payload, dict):
            candidates.extend([payload, payload.get("feature_schema"), payload.get("schema")])
            if isinstance(payload.get("objects"), list):
                candidates.extend(payload.get("objects")[:1])
        elif isinstance(payload, list) and payload:
            candidates.append(payload[0])
    for c in candidates:
        if isinstance(c, dict):
            h = c.get("feature_schema_hash") or (c.get("feature_schema") or {}).get("feature_schema_hash")
            if h:
                return {
                    "feature_schema_hash": h,
                    "feature_schema_version": c.get("feature_schema_version") or c.get("schema_version") or (c.get("feature_schema") or {}).get("schema_version"),
                    "feature_names": c.get("feature_names") or (c.get("feature_schema") or {}).get("feature_names"),
                    "horizons_min": c.get("horizons_min") or c.get("ML_FORECAST_HORIZONS_MIN"),
                    "target_encoding": c.get("target_encoding"),
                }
    return {}


def compare_sample_schema(sample_schema: dict, current_schema: dict | None = None) -> tuple[bool, str | None]:
    current_schema = current_schema or get_current_feature_schema()
    if not sample_schema or not sample_schema.get("feature_schema_hash"):
        return False, "legacy_missing_schema"
    if sample_schema.get("feature_schema_hash") == current_schema.get("feature_schema_hash"):
        return True, None
    if sample_schema.get("feature_names") and list(sample_schema["feature_names"]) != list(current_schema["feature_names"]):
        return False, "feature_count_mismatch"
    if sample_schema.get("horizons_min") and list(sample_schema["horizons_min"]) != list(current_schema["horizons_min"]):
        return False, "horizon_mismatch"
    if sample_schema.get("target_encoding") and sample_schema["target_encoding"] != current_schema["target_encoding"]:
        return False, "target_encoding_mismatch"
    if sample_schema.get("feature_count") and int(sample_schema["feature_count"]) != int(current_schema["num_features"]):
        return False, "feature_count_mismatch"
    return False, "feature_schema_mismatch"


def scan_training_sources(save_paths: dict | None = None, allow_legacy: bool | None = None) -> dict:
    import config
    paths = save_paths or config.SAVE_PATHS
    current = get_current_feature_schema()
    allow_legacy = bool(_cfg("ML_ALLOW_LEGACY_SAMPLES", False) if allow_legacy is None else allow_legacy)
    rejection_reasons = {}
    compatible = legacy = mismatch = accepted = rejected = 0
    obj_files = sorted(glob.glob(os.path.join(paths["objects"], "*.json")))
    weather_by_name = {os.path.basename(p): p for p in glob.glob(os.path.join(paths["weather"], "*.json"))}
    for op in obj_files:
        wp = weather_by_name.get(os.path.basename(op))
        if not wp:
            continue
        try:
            with open(op, encoding="utf-8") as f: objs = json.load(f)
            with open(wp, encoding="utf-8") as f: w = json.load(f)
        except Exception:
            continue
        ok, reason = compare_sample_schema(extract_source_schema(objs, w), current)
        if ok:
            compatible += 1; accepted += 1
        elif reason == "legacy_missing_schema":
            legacy += 1
            if allow_legacy: accepted += 1
            else: rejected += 1; rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
        else:
            mismatch += 1; rejected += 1; rejection_reasons[reason or "feature_schema_mismatch"] = rejection_reasons.get(reason or "feature_schema_mismatch", 0) + 1
    return {"current_schema": current, "compatible_samples": compatible, "legacy_samples": legacy, "mismatch_samples": mismatch, "used_samples": accepted, "rejected_samples": rejected, "rejection_reasons": rejection_reasons, "training_started": False}
