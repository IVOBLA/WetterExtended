from datetime import datetime, timedelta
import json
import os
import sys
import types


def _stub_optional_modules(monkeypatch):
    monkeypatch.setitem(sys.modules, "numpy", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "rasterio", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "scipy", types.SimpleNamespace(ndimage=types.SimpleNamespace()))


def test_detection_metadata_prefers_wms_over_download(tmp_path, monkeypatch):
    _stub_optional_modules(monkeypatch)
    import ir_cell_detection as det
    tif = tmp_path / "ir108_20260623144500.tif"
    tif.write_bytes(b"x")
    (tmp_path / "ir108_20260623144500.json").write_text(json.dumps({
        "observation_timestamp": "2026-06-23T14:45:00Z",
        "wms_timestamp": "2026-06-23T14:45:00Z",
        "downloaded_at_utc": "2026-06-23T14:58:00Z",
        "availability_latency_min": 13.0,
        "timestamp_source": "wms_time_dimension",
        "layer": "msg_fes:ir108",
        "scan_mode": "FES",
    }))
    meta = det._load_ir108_metadata(str(tif))
    assert meta["observation_timestamp"] == "2026-06-23T14:45:00Z"
    assert meta["timestamp_source"] == "wms_time_dimension"
    assert meta["availability_latency_min"] == 13.0


def test_detection_fallback_from_tiff_filename(tmp_path, monkeypatch):
    _stub_optional_modules(monkeypatch)
    import ir_cell_detection as det
    tif = tmp_path / "ir108_20260623144500.tif"
    tif.write_bytes(b"x")
    meta = det._load_ir108_metadata(str(tif))
    assert meta["observation_timestamp"] == "2026-06-23T14:45:00Z"
    assert meta["timestamp_source"] == "tiff_filename"


def test_ir_track_uses_observation_time_and_duration(monkeypatch, tmp_path):
    import ir_cell_tracking as tr
    monkeypatch.setattr(tr, "_SAVE_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(tr, "_STATE_FILE", str(tmp_path / "state.json"), raising=False)
    base = {
        "ir_id": "ir_0", "lat": 46.7, "lon": 14.3, "bt_min_k": 220, "bt_mean_k": 225,
        "area_px": 200, "overshooting_top": 0.0, "cloud_height_m": 9000,
        "cloud_height_confidence": 1, "cloud_height_source": "test", "height_stage": "cb",
        "ir_score": 1.0, "ir_stage": "ir_cb_precursor", "cape": 1000, "arome_li": -2,
        "tiff_file": "ir108_20260623140000.tif", "timestamp_source": "wms_time_dimension",
        "source_layer": "msg_fes:ir108", "scan_mode": "FES", "availability_latency_min": 13.0,
    }
    c1 = dict(base, observation_timestamp="2026-06-23T14:00:00Z", source_timestamp="2026-06-23T14:00:00Z", timestamp="2026-06-23T14:00:00Z")
    tracks = tr.update_ir_tracking([c1], "2026-06-23_14-00-00")
    assert tracks[0]["first_seen_observation_timestamp"] == "2026-06-23T14:00:00Z"
    assert tracks[0]["last_seen_observation_timestamp"] == "2026-06-23T14:00:00Z"
    c2 = dict(base, observation_timestamp="2026-06-23T14:45:00Z", source_timestamp="2026-06-23T14:45:00Z", timestamp="2026-06-23T14:45:00Z", tiff_file="ir108_20260623144500.tif")
    tracks = tr.update_ir_tracking([c2], "2026-06-23_14-45-00")
    assert tracks[0]["first_seen_timestamp"] == "2026-06-23T14:00:00Z"
    assert tracks[0]["last_seen_observation_timestamp"] == "2026-06-23T14:45:00Z"
    assert tracks[0]["source_timestamp"] == "2026-06-23T14:45:00Z"
    assert tracks[0]["cloud_age_min"] == 45.0


def test_main_freshness_uses_observation_not_mtime(monkeypatch, tmp_path):
    cv2_stub = types.SimpleNamespace()
    monkeypatch.setitem(sys.modules, "cv2", cv2_stub)
    for name in ["radar_download", "object_tracking", "weather_api", "prediction", "size_regressor", "kmz_export", "visualize_radar", "movement_gif", "upload_utilities", "fetch_700hpa_wind_per_object_slim", "assign_cape_from_forecast", "geo_utils", "cloud_height_from_eumetview", "optical_flow_features", "radar_frame_selection", "fetch_arome_openmeteo", "fetch_synoptic_features", "orographic_module", "fetch_openmeteo_extended", "fetch_geosphere_nowcast", "compute_convective_indices", "fetch_tawes_gust", "ir_cell_detection"]:
        monkeypatch.setitem(sys.modules, name, types.SimpleNamespace(**{
            "download_kmz": lambda *a, **k: None, "detect_and_track_objects": lambda *a, **k: [],
            "get_weather_data": lambda *a, **k: None, "predict_positions": lambda *a, **k: None,
            "save_forecast_as_kmz": lambda *a, **k: None, "create_visualized_radar": lambda *a, **k: None,
            "create_movement_gif": lambda *a, **k: None, "upload_file_ftp": lambda *a, **k: None,
            "fetch_and_assign_700hpa_wind": lambda *a, **k: None, "assign_cape": lambda *a, **k: None,
            "get_roi_from_bbox": lambda *a, **k: None, "kml_bounds": lambda *a, **k: None,
            "assign_cloud_top_height": lambda *a, **k: None, "assign_optical_flow_to_objects": lambda *a, **k: None,
            "remember_valid_radar_path": lambda *a, **k: None, "select_optflow_prev_radar_path": lambda *a, **k: None,
            "assign_arome_to_objects": lambda *a, **k: None, "assign_synoptic_features": lambda *a, **k: None,
            "assign_orographic_scores": lambda *a, **k: None, "assign_extended_openmeteo": lambda *a, **k: None,
            "assign_nowcast_to_objects": lambda *a, **k: None, "assign_convective_indices": lambda *a, **k: None,
            "fetch_tawes_stations": lambda *a, **k: None, "max_gust_near": lambda *a, **k: None, "nearest_station_wind": lambda *a, **k: None,
            "detect_ir_cells": lambda *a, **k: [],
        }))
    import main
    cloud = tmp_path / "cloud"
    cloud.mkdir()
    tif = cloud / "ir108_20260623144500.tif"
    tif.write_bytes(b"x")
    old = datetime.utcnow() - timedelta(minutes=120)
    meta_ts = old.strftime("%Y-%m-%dT%H:%M:%SZ")
    (cloud / "ir108_20260623144500.json").write_text(json.dumps({"observation_timestamp": meta_ts}))
    now = datetime.utcnow().timestamp()
    os.utime(tif, (now, now))
    monkeypatch.setitem(main.SAVE_PATHS, "cloud", str(cloud))
    assert main._latest_ir_tiff_fresh(max_age_min=20) is False
