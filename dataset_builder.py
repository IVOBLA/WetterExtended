import bisect
import glob
import json
import os
import tempfile
from datetime import datetime, timedelta
from math import cos, pi, sin

import importlib
import importlib.util
np = importlib.import_module("numpy") if importlib.util.find_spec("numpy") else None

joblib = importlib.import_module("joblib") if importlib.util.find_spec("joblib") else None
pd = importlib.import_module("pandas") if importlib.util.find_spec("pandas") else None
StandardScaler = None
if importlib.util.find_spec("sklearn"):
    StandardScaler = importlib.import_module("sklearn.preprocessing").StandardScaler


try:
    from debug_utils import debug_log
except Exception:
    def debug_log(message):
        print(message)

try:
    from geo_utils import pixel_to_geo
except Exception:
    def pixel_to_geo(x, y):
        return 0.0, 0.0

try:
    from utils import find_nearest_station
except Exception:
    def find_nearest_station(lat, lon, stations):
        return None

from config import (
    FRAME_INTERVAL_MIN,
    LOOP_INTERVAL_NO_CELLS_S,
    ML_CELL_FEATURES,
    ML_FORECAST_HORIZONS_MIN,
    ML_SEQUENCE_LENGTH,
    ML_STATION_FEATURES,
    ML_TARGET_ENCODING,
    RADAR_INGEST_GAP_WARN_FACTOR,
    RADAR_INGEST_GAP_CRITICAL_FACTOR,
    SAVE_PATHS,
)

_rc = importlib.import_module("runtime_config") if importlib.util.find_spec("runtime_config") else None


def _radar_ingest_gap_thresholds():
    """B298: Admin-/runtime-editierbare Schwellwerte (Vielfaches von
    expected_interval_min) fuer die Radar-Ingest-Gesundheitsbewertung."""
    warn = float(RADAR_INGEST_GAP_WARN_FACTOR)
    crit = float(RADAR_INGEST_GAP_CRITICAL_FACTOR)
    if _rc is not None:
        try:
            warn = float(_rc.get("RADAR_INGEST_GAP_WARN_FACTOR", warn))
            crit = float(_rc.get("RADAR_INGEST_GAP_CRITICAL_FACTOR", crit))
        except Exception:
            pass
    return warn, crit

from data_quality import validate_sample
from feature_schema import compare_sample_schema, extract_source_schema, get_current_feature_schema, schema_metadata



def _expected_radar_interval_min(hours: int) -> float:
    """B316: Leitet den erwarteten Radar-Frame-Takt dynamisch aus der tatsaechlichen
    Zellaktivitaet im Bewertungsfenster ab, statt immer den aktiven Takt
    (FRAME_INTERVAL_MIN) anzunehmen. Ohne Zellen im Fenster laeuft der Loop bewusst
    nur alle LOOP_INTERVAL_NO_CELLS_S Sekunden (Ressourcenschonung, siehe B302/B303) —
    das ist kein Ingest-Fehler und darf die Coverage-Bewertung nicht als 'critical'
    einstufen. Bei jeglicher gefundener Zellaktivitaet im Fenster wird konservativ der
    schnellere aktive Takt erwartet."""
    try:
        obj_dir = SAVE_PATHS.get("objects", "train_data/objects/")
        cutoff = datetime.utcnow() - timedelta(hours=max(1, int(hours)))
        for path in sorted(glob.glob(os.path.join(obj_dir, "*.json")), reverse=True):
            try:
                ts = _parse_ts(path)
            except Exception:
                continue
            if ts < cutoff:
                break
            try:
                with open(path, "r", encoding="utf-8") as f:
                    objs = json.load(f)
            except Exception:
                continue
            if isinstance(objs, list) and len(objs) > 0:
                return float(FRAME_INTERVAL_MIN)
    except Exception:
        pass
    return float(LOOP_INTERVAL_NO_CELLS_S) / 60.0


def compute_radar_ingest_gaps(expected_interval_min, hours=24):
    """B278: Quantifiziert lokale Radar-Ingest-Lücken ohne Fremdrequests."""
    try:
        interval_min = max(1, int(expected_interval_min))
    except Exception:
        interval_min = 5
    try:
        hours = max(1, int(hours))
    except Exception:
        hours = 24

    radar_dir = SAVE_PATHS.get("radar", "train_data/radar/")
    png_paths = sorted(glob.glob(os.path.join(radar_dir, "*.png")))
    now = datetime.utcnow()
    cutoff = now - timedelta(hours=hours)
    present_ts = []
    for path in png_paths:
        try:
            ts = _parse_ts(path)
        except Exception:
            continue
        if cutoff <= ts <= now:
            present_ts.append(ts.replace(second=0, microsecond=0))

    if present_ts:
        start = min(cutoff.replace(second=0, microsecond=0), min(present_ts))
        end = max(present_ts)
    else:
        start = cutoff.replace(second=0, microsecond=0)
        end = now.replace(second=0, microsecond=0)

    expected = []
    cur = start
    step = timedelta(minutes=interval_min)
    while cur <= end:
        expected.append(cur)
        cur += step

    present_set = set(present_ts)
    # B321: Statt exaktem Set-Mitgliedschaftstest (der bei einem an cutoff/now statt
    # an der realen Frame-Phase verankerten Erwartungsraster fast immer fehlschlaegt,
    # da z.B. :05/:20/:35/:50-Frames selten exakt auf :27/:42/:57/:12-Slots fallen)
    # wird jedem Erwartungsslot der naechstgelegene tatsaechliche Frame innerhalb
    # einer Toleranz von interval_min/2 zugeordnet. Nur echte Luecken (kein Frame in
    # der Naehe) gelten als 'missing'.
    _sorted_present = sorted(present_set)
    _tolerance = timedelta(minutes=interval_min / 2.0)
    missing = []
    for slot in expected:
        idx = bisect.bisect_left(_sorted_present, slot)
        candidates = []
        if idx < len(_sorted_present):
            candidates.append(_sorted_present[idx])
        if idx > 0:
            candidates.append(_sorted_present[idx - 1])
        if not candidates or min(abs(slot - c) for c in candidates) > _tolerance:
            missing.append(slot)
    longest_gap_min = 0.0
    sorted_present = sorted(present_set)
    for prev, nxt in zip(sorted_present, sorted_present[1:]):
        longest_gap_min = max(longest_gap_min, (nxt - prev).total_seconds() / 60.0)
    if not sorted_present and expected:
        longest_gap_min = len(expected) * interval_min

    # B298: Health-/Alarmklassifikation, unterscheidet "ARSO liefert seltener
    # als erwartet" (viele kurze Luecken, geringe Coverage) von echten
    # Ingest-Ausfaellen (einzelne lange Luecke). health_status fasst beides fuer
    # Monitoring/Admin-Panel zusammen.
    warn_factor, critical_factor = _radar_ingest_gap_thresholds()
    gap_factor = (longest_gap_min / interval_min) if interval_min else 0.0
    if gap_factor >= critical_factor:
        health_status = "critical"
    elif gap_factor > warn_factor:
        health_status = "warning"
    else:
        health_status = "ok"
    # B321: Coverage niemals >1.0 - eine feinere reale Kadenz als das grobe
    # Erwartungsraster (z.B. 5-min-Frames waehrend aktiver Zellen) ist keine
    # "Uebererfuellung", sondern soll als vollstaendige Abdeckung (100%) gewertet
    # werden.
    coverage_ratio = (
        round(min(len(present_set), len(expected)) / len(expected), 4)
        if expected
        else None
    )

    result = {
        "computed_at_utc": now.isoformat(timespec="seconds") + "Z",
        "expected_interval_min": interval_min,
        "hours": hours,
        "expected_frames": len(expected),
        "present_frames": len(present_set),
        "coverage_ratio": coverage_ratio,
        "missing_timestamps": [ts.isoformat(timespec="minutes") for ts in missing],
        "longest_gap_min": round(longest_gap_min, 3),
        "health_status": health_status,
        "health_thresholds": {"warn_factor": warn_factor, "critical_factor": critical_factor},
    }

    out_path = os.path.join(SAVE_PATHS.get("evaluation", "train_data/evaluation/"), "radar_ingest_gaps.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".radar_ingest_gaps.", suffix=".tmp", dir=os.path.dirname(out_path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        os.replace(tmp, out_path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except Exception:
                pass
    return result

def _schema_policy_allows_legacy():
    try:
        import runtime_config as _rc
        return bool(_rc.get("ML_ALLOW_LEGACY_SAMPLES", False))
    except Exception:
        try:
            from config import ML_ALLOW_LEGACY_SAMPLES
            return bool(ML_ALLOW_LEGACY_SAMPLES)
        except Exception:
            return False



def _get_ds_horizons() -> list:
    """
    Gibt die aktuell konfigurierten Forecast-Horizonte zurück.
    Priorisiert runtime_config (Admin-Panel), Fallback: config.py.
    P23: Damit Dataset-Build und Training dieselben Horizonte wie der Forecast nutzen.
    """
    try:
        import runtime_config as _rc_ds
        return list(_rc_ds.get("ML_FORECAST_HORIZONS_MIN", ML_FORECAST_HORIZONS_MIN))
    except Exception:
        return list(ML_FORECAST_HORIZONS_MIN)


def _safe_float(value):
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _parse_ts(path):
    name = os.path.splitext(os.path.basename(path))[0]
    return datetime.strptime(name, "%Y-%m-%d_%H-%M-%S")


def _frame_features(obj, stations, ts):
    cell_features = [_safe_float(obj.get(key, 0.0)) for key in ML_CELL_FEATURES]

    # Fix P02: Lat/Lon direkt aus dem Objekt nehmen (object_tracking.py speichert
    # die geografische Position bereits korrekt mit SKALIERTEN Koordinaten).
    # Fallback nur wenn lat/lon fehlen: pixel_to_geo mit UPSCALE-korrigierten
    # Koordinaten (obj["x"]/y sind pre-upscale, pixel_to_geo erwartet skaliert).
    _lat_obj = obj.get("lat")
    _lon_obj = obj.get("lon")
    if _lat_obj is not None and _lon_obj is not None:
        lat = float(_lat_obj)
        lon = float(_lon_obj)
    else:
        try:
            from config import UPSCALE_FACTOR as _UF_DS
        except Exception:
            _UF_DS = 3.0
        _ox = _safe_float(obj.get("x", 0.0)) * float(_UF_DS)
        _oy = _safe_float(obj.get("y", 0.0)) * float(_UF_DS)
        lat, lon = pixel_to_geo(_ox, _oy)

    nearest_station = find_nearest_station(lat, lon, stations) if stations else None
    station_features = [
        _safe_float(nearest_station.get(key, 0.0)) if nearest_station else 0.0
        for key in ML_STATION_FEATURES
    ]

    hour_fraction = (ts.hour * 60 + ts.minute) / (24 * 60)
    hour_angle = 2 * pi * hour_fraction
    month_fraction = (ts.month - 1) / 12.0
    month_angle = 2 * pi * month_fraction
    time_features = [sin(hour_angle), cos(hour_angle), sin(month_angle), cos(month_angle)]

    return cell_features + station_features + time_features



def _empty_result():
    schema = get_current_feature_schema()
    return {"X": [], "y": [], "y_raw": [], "ids": [], "rejected_samples": 0, "rejection_reasons": {}, "feature_schema_hash": schema["feature_schema_hash"], "schema_compatible_samples": 0, "schema_legacy_samples": 0, "schema_mismatch_samples": 0}


def _dependencies_available():
    missing = []
    if np is None:
        missing.append("numpy")
    if joblib is None:
        missing.append("joblib")
    if pd is None:
        missing.append("pandas")
    if StandardScaler is None:
        missing.append("scikit-learn")
    return missing

def _current_models_dir():
    return os.path.join(SAVE_PATHS["models"], "current")


def load_scalers():
    if joblib is None:
        return None, None

    base_dir = _current_models_dir()
    scaler_x_path = os.path.join(base_dir, "scaler_X.joblib")
    scaler_y_path = os.path.join(base_dir, "scaler_y.joblib")
    if not (os.path.exists(scaler_x_path) and os.path.exists(scaler_y_path)):
        return None, None
    return joblib.load(scaler_x_path), joblib.load(scaler_y_path)


def _fit_nan_aware_standard_scaler(values):
    scaler = StandardScaler()
    col_mean = np.nanmean(values, axis=0)
    col_std = np.nanstd(values, axis=0)
    col_mean = np.where(np.isnan(col_mean), 0.0, col_mean)
    col_std = np.where(np.isnan(col_std) | (col_std == 0.0), 1.0, col_std)
    scaler.mean_ = col_mean
    scaler.scale_ = col_std
    scaler.var_ = col_std ** 2
    scaler.n_features_in_ = values.shape[1]
    scaled = (values - col_mean) / col_std
    return scaler, scaled


def build_dataset(model_save_dir=None):
    try:
        # B316: dynamischer Takt statt immer FRAME_INTERVAL_MIN — vermeidet
        # faelschliche 'critical'-Einstufung im zellfreien Ruhebetrieb.
        compute_radar_ingest_gaps(_expected_radar_interval_min(24), hours=24)
    except Exception as exc:
        debug_log(f"[DATASET] Radar-Ingest-Lücken konnten nicht berechnet werden: {exc}")

    missing_deps = _dependencies_available()
    if missing_deps:
        debug_log(f"[DATASET] Abbruch: fehlende Abhängigkeiten: {', '.join(missing_deps)}")
        return _empty_result()

    obj_files = sorted(glob.glob(os.path.join(SAVE_PATHS["objects"], "*.json")))
    wthr_files = sorted(glob.glob(os.path.join(SAVE_PATHS["weather"], "*.json")))

    paired = []
    weather_by_name = {os.path.basename(p): p for p in wthr_files}
    for op in obj_files:
        base = os.path.basename(op)
        wp = weather_by_name.get(base)
        if wp:
            paired.append((op, wp))

    if not paired:
        debug_log("[DATASET] Keine passenden Objekt/Wetter-Dateipaare gefunden.")
        return _empty_result()

    # Fix #5: Timestamp-basierte Horizont-Suche (statt fester h//5 Frame-Index-Annahme)
    # Hintergrund: Live-Loop kann 2-Min-Intervalle haben → h//5 wäre falsch
    from datetime import timedelta as _td_ds
    _DS_TOL_FACTOR  = 0.5   # 50 % des Horizonts als Toleranz
    _DS_MIN_TOL_MIN = 3.0   # mindestens 3 Minuten Toleranz
    # min_required: Sequenz + mind. 1 zukünftiger Frame
    min_required = ML_SEQUENCE_LENGTH + 1
    if len(paired) < min_required:
        debug_log(f"[DATASET] Zu wenige Frames: {len(paired)} < {min_required}.")
        return _empty_result()

    frames = []
    for op, wp in paired:
        try:
            frames.append((op, wp, _parse_ts(op), _load_json(op), _load_json(wp)))
        except Exception as exc:
            debug_log(f"[DATASET] Fehler beim Laden von {op}: {exc}")

    X_rows, y_rows, ids = [], [], []
    tabular_rows = []
    rejection_reasons = {}
    n_rejected = 0
    current_schema = get_current_feature_schema()
    allow_legacy = _schema_policy_allows_legacy()
    schema_compatible_samples = 0
    schema_legacy_samples = 0
    schema_mismatch_samples = 0

    # Fix #5: Kein festes max_h_steps mehr — Timestamp-Suche erledigt die Begrenzung
    for i in range(ML_SEQUENCE_LENGTH - 1, len(frames)):
        seq_slice = frames[i - ML_SEQUENCE_LENGTH + 1 : i + 1]
        now_ts = seq_slice[-1][2]
        compatible_slice = True
        slice_reason = None
        for _op_s, _wp_s, _ts_s, _objs_s, _w_s in seq_slice:
            _ok_schema, _reason_schema = compare_sample_schema(extract_source_schema(_objs_s, _w_s), current_schema)
            if _ok_schema:
                continue
            if _reason_schema == "legacy_missing_schema":
                schema_legacy_samples += 1
                if allow_legacy:
                    continue
            else:
                schema_mismatch_samples += 1
            compatible_slice = False
            slice_reason = _reason_schema or "feature_schema_mismatch"
            break
        if not compatible_slice:
            n_rejected += 1
            rejection_reasons[slice_reason] = rejection_reasons.get(slice_reason, 0) + 1
            continue
        schema_compatible_samples += 1
        # B332: cell_id (stabile fachliche Identitaet, ueberlebt Merge/Split/
        # IR-Precursor-Bruecken via cell_lineage.py) statt der volatilen
        # Tracking-'id' als Sequenzschluessel. Fallback auf 'id' fuer
        # Legacy-Frames ohne cell_id-Feld.
        seq_obj_maps = [
            {str(o.get("cell_id") or o.get("id")): o for o in frm[3]
             if isinstance(o, dict) and (o.get("cell_id") or o.get("id") is not None)}
            for frm in seq_slice
        ]

        common_ids = set(seq_obj_maps[0].keys())
        for m in seq_obj_maps[1:]:
            common_ids &= set(m.keys())

        if not common_ids:
            continue

        # Fix #5: Besten Frame per echtem Timestamp suchen
        future_obj_maps = []
        for h_min in _get_ds_horizons():
            target_ts = now_ts + _td_ds(minutes=h_min)
            tol       = _td_ds(minutes=max(h_min * _DS_TOL_FACTOR, _DS_MIN_TOL_MIN))
            best_idx, best_diff = None, _td_ds(days=999)
            for j in range(i + 1, len(frames)):
                diff = abs(frames[j][2] - target_ts)
                if diff < best_diff:
                    best_diff, best_idx = diff, j
                if frames[j][2] > target_ts + tol:
                    break  # frames sind sortiert → kein besserer Kandidat mehr
            if best_idx is not None and best_diff <= tol:
                fut_objs = frames[best_idx][3]
            else:
                fut_objs = []
                debug_log(f"[DATASET] Kein Frame für h={h_min}min nahe {target_ts} (best_diff={best_diff})")
            future_obj_maps.append(
                # B332: gleicher Schluessel wie bei seq_obj_maps (cell_id
                # bevorzugt, Fallback id) -- sonst wuerde targets/common_ids
                # inkonsistent gegen unterschiedliche Identitaeten gematcht.
                {str(o.get("cell_id") or o.get("id")): o for o in fut_objs
                 if isinstance(o, dict) and (o.get("cell_id") or o.get("id") is not None)}
            )

        for oid in common_ids:
            # P-T08: Per-Horizont-Maskierung. Sequenz wird verwertet sobald
            # MINDESTENS EIN Horizont verfügbar ist; fehlende Horizonte → NaN.
            if all(oid not in fmap for fmap in future_obj_maps):
                continue  # kein einziger Horizont verfügbar → unbrauchbar

            seq_features = []
            seq_objects = []
            valid = True
            for op, wp, ts, objs, stations in seq_slice:
                # B332: Lookup gegen denselben Schluessel wie beim Aufbau der
                # seq_obj_maps (cell_id bevorzugt, Fallback id).
                obj = next(
                    (o for o in objs if str(o.get("cell_id") or o.get("id")) == oid),
                    None,
                )
                if obj is None:
                    valid = False
                    break
                seq_features.append(_frame_features(obj, stations, ts))
                seq_objects.append(obj)

            if not valid:
                continue

            # P58: Delta-Encoding — Ziel ist die Verschiebung relativ zur aktuellen
            # Position (seq_objects[-1]). Absolute Konvention bleibt via Config wählbar.
            _now_x = _safe_float(seq_objects[-1].get("x", 0.0))
            _now_y = _safe_float(seq_objects[-1].get("y", 0.0))
            targets = []
            for fmap in future_obj_maps:
                if oid in fmap:
                    fo = fmap[oid]
                    _fx = _safe_float(fo.get("x", 0.0))
                    _fy = _safe_float(fo.get("y", 0.0))
                    if ML_TARGET_ENCODING == "delta":
                        targets.extend([_fx - _now_x, _fy - _now_y])
                    else:
                        targets.extend([_fx, _fy])
                else:
                    targets.extend([float("nan"), float("nan")])  # maskierter Horizont

            ok, reason = validate_sample(seq_features, targets, seq_context=seq_objects)
            if not ok:
                n_rejected += 1
                rejection_reasons[reason or "unknown"] = rejection_reasons.get(reason or "unknown", 0) + 1
                continue

            X_rows.append(seq_features)
            y_rows.append(targets)
            _meta = schema_metadata(seq_slice[-1][0], seq_slice[-1][1])
            ids.append({"id": oid, "timestamp": now_ts.strftime("%Y-%m-%d_%H-%M-%S"), **_meta})

            tab_row = {k: v for k, v in zip(ML_CELL_FEATURES + ML_STATION_FEATURES + ["hour_sin", "hour_cos", "month_sin", "month_cos"], seq_features[-1])}
            tab_row.update(_meta)
            for h_min, (tx, ty) in zip(_get_ds_horizons(), np.array(targets).reshape(-1, 2)):
                tab_row[f"target_x_{h_min}"] = tx
                tab_row[f"target_y_{h_min}"] = ty
            tab_row["id"] = oid
            tab_row["timestamp"] = now_ts.strftime("%Y-%m-%d_%H-%M-%S")
            tabular_rows.append(tab_row)

    if not X_rows:
        debug_log("[DATASET] Keine gültigen Sequenzen gefunden.")
        return _empty_result()

    X = np.asarray(X_rows, dtype=float)
    y_raw = np.asarray(y_rows, dtype=float)

    # B323: Diagnose der Ziel-Verschiebungsverteilung (erster Horizont). Rein
    # diagnostisch, aendert kein Trainings-/Sampling-Verhalten. Soll klaeren, ob ein
    # hoher Anteil quasi-stationaerer Zellen (siehe B315) die Zielverteilung
    # verschiebt und dadurch den LSTM-Validierungsverlust bei Retrains beeinflusst.
    target_displacement_stats = {}
    try:
        if y_raw.shape[0] > 0 and y_raw.shape[1] >= 2:
            _disp = np.sqrt(y_raw[:, 0] ** 2 + y_raw[:, 1] ** 2)
            _disp_valid = _disp[~np.isnan(_disp)]
            if _disp_valid.size > 0:
                target_displacement_stats = {
                    "horizon0_median_px": round(float(np.median(_disp_valid)), 3),
                    "horizon0_mean_px": round(float(np.mean(_disp_valid)), 3),
                    "horizon0_p10_px": round(float(np.percentile(_disp_valid, 10)), 3),
                    "horizon0_p90_px": round(float(np.percentile(_disp_valid, 90)), 3),
                    "quasi_stationary_fraction_lt2px": round(float(np.mean(_disp_valid < 2.0)), 4),
                    "sample_count": int(_disp_valid.size),
                }
    except Exception as exc:
        debug_log(f"[DATASET] target_displacement_stats fehlgeschlagen: {exc}")

    effective_model_dir = model_save_dir
    if effective_model_dir is not None:
        os.makedirs(effective_model_dir, exist_ok=True)
    os.makedirs(SAVE_PATHS["dataset"], exist_ok=True)

    X_flat = X.reshape(-1, X.shape[-1])
    scaler_X, X_flat_scaled = _fit_nan_aware_standard_scaler(X_flat)
    X_scaled = X_flat_scaled.reshape(X.shape)

    # P-T08: NaN-bewusste Standardisierung. y_raw enthält NaN für maskierte
    # Horizonte. StandardScaler kann NaN nicht fitten → Mittel/Streuung pro
    # Spalte aus den gültigen Werten berechnen und in den Scaler schreiben,
    # damit inverse_transform im Inferenz-Pfad korrekt bleibt. NaN bleibt NaN.
    scaler_y, y_scaled = _fit_nan_aware_standard_scaler(y_raw)

    if effective_model_dir is not None:
        joblib.dump(scaler_X, os.path.join(effective_model_dir, "scaler_X.joblib"))
        joblib.dump(scaler_y, os.path.join(effective_model_dir, "scaler_y.joblib"))

    np.savez(
        os.path.join(SAVE_PATHS["dataset"], "dataset.npz"),
        X=X_scaled,
        y=y_scaled,
        y_raw=y_raw,
        ids=np.asarray(ids, dtype=object),
    )

    pd.DataFrame(tabular_rows).to_parquet(os.path.join(SAVE_PATHS["dataset"], "tabular.parquet"), index=False)

    debug_log(f"[DATASET] Datensatz gebaut: X={X_scaled.shape}, y={y_scaled.shape}")
    debug_log(f"[DATASET] Feature schema: {current_schema.get('feature_schema_hash')} (version={current_schema.get('schema_version')})")
    debug_log(f"[DATASET] Kompatible Samples: {schema_compatible_samples}")
    debug_log(f"[DATASET] Legacy: {schema_legacy_samples}")
    debug_log(f"[DATASET] Schema mismatch: {schema_mismatch_samples}")
    debug_log(f"[DATASET] Verwendet: {len(X_rows)}")
    debug_log(f"[DATASET] Abgelehnt: {n_rejected} (reasons: {rejection_reasons})")
    # Timestamps pro Sample extrahieren (aus ids-Liste, 1:1 zu X/y)
    _ts_list = [entry.get("timestamp", "") for entry in ids]
    return {"X": X_scaled, "y": y_scaled, "y_raw": y_raw, "ids": ids, "timestamps": _ts_list, "rejected_samples": n_rejected, "rejection_reasons": rejection_reasons, "feature_schema_hash": current_schema["feature_schema_hash"], "feature_schema": current_schema, "schema_compatible_samples": schema_compatible_samples, "schema_legacy_samples": schema_legacy_samples, "schema_mismatch_samples": schema_mismatch_samples, "target_displacement_stats": target_displacement_stats}


def _merge_contaminated(o_now, o_fut):
    """P-M04: True, wenn Jetzt- ODER Ziel-Frame eine Merge-Diskontinuität trägt.
    Schließt das Sample vom intensified-Label-Training aus (Merge-Artefakt)."""
    try:
        if int(o_now.get("merge_discontinuity", 0)) == 1:
            return True
        if int(o_fut.get("merge_discontinuity", 0)) == 1:
            return True
    except (AttributeError, TypeError, ValueError):
        return False
    return False


def build_classification_dataset():
    missing_deps = _dependencies_available()
    if missing_deps:
        debug_log(f"[DATASET-CLS] Abbruch: fehlende Abhängigkeiten: {', '.join(missing_deps)}")
        return {"X": [], "y": [], "samples": 0, "positive_samples": 0}

    obj_files = sorted(glob.glob(os.path.join(SAVE_PATHS["objects"], "*.json")))
    wthr_files = sorted(glob.glob(os.path.join(SAVE_PATHS["weather"], "*.json")))
    weather_by_name = {os.path.basename(p): p for p in wthr_files}
    paired = [(op, weather_by_name[os.path.basename(op)]) for op in obj_files if os.path.basename(op) in weather_by_name]
    if not paired:
        debug_log("[DATASET-CLS] Keine passenden Objekt/Wetter-Dateipaare gefunden.")
        return {"X": [], "y": [], "samples": 0, "positive_samples": 0}

    # Fix R1: Timestamp-Suche statt fester 5-min-Annahme (analog build_dataset)
    from datetime import timedelta as _td_cls
    _CLS_HORIZON_MIN   = 20       # Intensivierungshorizont: 20 Minuten
    _CLS_TOL_FACTOR    = 0.5      # 50 % Toleranz
    _CLS_MIN_TOL_MIN   = 3.0      # mindestens 3 Minuten
    min_required = ML_SEQUENCE_LENGTH + 1
    if len(paired) < min_required:
        debug_log(f"[DATASET-CLS] Zu wenige Frames: {len(paired)} < {min_required}.")
        return {"X": [], "y": [], "samples": 0, "positive_samples": 0}

    frames = []
    for op, wp in paired:
        try:
            frames.append((op, wp, _parse_ts(op), _load_json(op), _load_json(wp)))
        except Exception as exc:
            debug_log(f"[DATASET-CLS] Fehler beim Laden von {op}: {exc}")

    rows = []
    current_schema = get_current_feature_schema()
    allow_legacy = _schema_policy_allows_legacy()
    schema_compatible_samples = 0
    schema_legacy_samples = 0
    schema_mismatch_samples = 0
    n_rejected = 0
    rejection_reasons = {}
    # Fix R1: Kein festes horizon_step mehr — Timestamp-Suche
    for i in range(ML_SEQUENCE_LENGTH - 1, len(frames)):
        seq_slice = frames[i - ML_SEQUENCE_LENGTH + 1 : i + 1]
        now_ts = seq_slice[-1][2]
        compatible_slice = True
        slice_reason = None
        for _op_s, _wp_s, _ts_s, _objs_s, _w_s in seq_slice:
            _ok_schema, _reason_schema = compare_sample_schema(extract_source_schema(_objs_s, _w_s), current_schema)
            if _ok_schema:
                continue
            if _reason_schema == "legacy_missing_schema":
                schema_legacy_samples += 1
                if allow_legacy:
                    continue
            else:
                schema_mismatch_samples += 1
            compatible_slice = False
            slice_reason = _reason_schema or "feature_schema_mismatch"
            break
        if not compatible_slice:
            n_rejected += 1
            rejection_reasons[slice_reason] = rejection_reasons.get(slice_reason, 0) + 1
            continue
        schema_compatible_samples += 1
        # B332: cell_id bevorzugt, Fallback id (siehe build_dataset() oben).
        now_map = {str(o.get("cell_id") or o.get("id")): o for o in seq_slice[-1][3]
                   if isinstance(o, dict) and (o.get("cell_id") or o.get("id") is not None)}

        # Besten Frame ~20 min in der Zukunft suchen (Timestamp-basiert)
        target_ts  = now_ts + _td_cls(minutes=_CLS_HORIZON_MIN)
        tol        = _td_cls(minutes=max(_CLS_HORIZON_MIN * _CLS_TOL_FACTOR, _CLS_MIN_TOL_MIN))
        best_idx, best_diff = None, _td_cls(days=999)
        for j in range(i + 1, len(frames)):
            diff = abs(frames[j][2] - target_ts)
            if diff < best_diff:
                best_diff, best_idx = diff, j
            if frames[j][2] > target_ts + tol:
                break
        if best_idx is None or best_diff > tol:
            continue
        fut_objs = frames[best_idx][3]
        fut_map  = {str(o.get("cell_id") or o.get("id")): o for o in fut_objs
                    if isinstance(o, dict) and (o.get("cell_id") or o.get("id") is not None)}

        common_ids = set(now_map.keys()) & set(fut_map.keys())
        if not common_ids:
            continue

        for oid in common_ids:
            seq_features = []
            seq_objects = []
            valid = True
            for _, _, ts, objs, stations in seq_slice:
                # B332: Lookup gegen denselben Schluessel wie now_map/fut_map.
                obj = next((o for o in objs if str(o.get("cell_id") or o.get("id")) == oid), None)
                if obj is None:
                    valid = False
                    break
                seq_features.append(_frame_features(obj, stations, ts))
                seq_objects.append(obj)
            if not valid:
                continue

            obj_now = now_map[oid]
            obj_fut = fut_map[oid]
            # P-M04: Merge-kontaminierte Frames ausschließen (künstlicher Sprung).
            if _merge_contaminated(obj_now, obj_fut):
                continue
            core_now = _safe_float(obj_now.get("core_ratio", 0.0))
            core_fut = _safe_float(obj_fut.get("core_ratio", 0.0))
            size_now = max(_safe_float(obj_now.get("size", 0.0)), 1e-6)
            size_fut = _safe_float(obj_fut.get("size", 0.0))
            intensified = int((core_fut - core_now) >= 0.05 or (size_fut / size_now) >= 1.2)

            row = {
                k: v for k, v in zip(
                    ML_CELL_FEATURES + ML_STATION_FEATURES + ["hour_sin", "hour_cos", "month_sin", "month_cos"],
                    seq_features[-1],
                )
            }
            row["intensified"] = intensified
            row["id"] = oid
            row["timestamp"] = now_ts.strftime("%Y-%m-%d_%H-%M-%S")
            rows.append(row)

    if not rows:
        debug_log("[DATASET-CLS] Keine gültigen Samples gefunden.")
        return {"X": [], "y": [], "samples": 0, "positive_samples": 0}

    df = pd.DataFrame(rows)
    out_path = os.path.join(SAVE_PATHS["dataset"], "tabular_classification.parquet")
    os.makedirs(SAVE_PATHS["dataset"], exist_ok=True)
    df.to_parquet(out_path, index=False)
    positives = int(df["intensified"].sum())
    debug_log(f"[DATASET-CLS] Datensatz gebaut: samples={len(df)}, positives={positives}")
    return {"X": df.drop(columns=["intensified", "id", "timestamp"]), "y": df["intensified"], "samples": len(df), "positive_samples": positives}


if __name__ == "__main__":
    build_dataset()


def build_regression_intensity_dataset():
    """Leitet an intensity_regression.py weiter (Stub für Importe aus dataset_builder)."""
    try:
        from intensity_regression import build_regression_intensity_dataset as _impl
        return _impl()
    except ImportError:
        debug_log("[DATASET] intensity_regression.py nicht gefunden")
        return None
