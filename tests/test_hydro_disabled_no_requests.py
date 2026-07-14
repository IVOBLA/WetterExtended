import sys
import types


def _fail_network(*args, **kwargs):
    raise AssertionError("Hydro-Netzwerkfunktion darf bei HYDRO_ENABLED=false nicht aufgerufen werden")


def test_fetch_hydro_live_disabled_never_calls_network(monkeypatch, tmp_path):
    import hydro_fetch

    monkeypatch.setenv("HYDRO_ENABLED", "false")
    monkeypatch.setattr(hydro_fetch, "_LIVE_DIR", tmp_path)
    monkeypatch.setattr(hydro_fetch, "LATEST_FILE", tmp_path / "latest_hydro.json")
    monkeypatch.setattr(hydro_fetch, "STATUS_FILE", tmp_path / "hydro_status.json")
    monkeypatch.setitem(__import__("sys").modules, "http_retry", types.SimpleNamespace(retry_get=_fail_network))

    result = hydro_fetch.fetch_hydro_live(force=True)

    assert result["stations"] == []
    assert result["status"]["error"] == "hydro_disabled"
    assert result["status"]["station_count"] == 0


def test_scheduler_hydro_disabled_runs_without_live_request_or_error_log(monkeypatch):
    import hydro_fetch

    class _Trigger:
        def __init__(self, *args, **kwargs):
            pass

    monkeypatch.setitem(sys.modules, "apscheduler", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "apscheduler.schedulers", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "apscheduler.schedulers.blocking", types.SimpleNamespace(BlockingScheduler=object))
    monkeypatch.setitem(sys.modules, "apscheduler.triggers", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "apscheduler.triggers.cron", types.SimpleNamespace(CronTrigger=_Trigger))
    monkeypatch.setitem(sys.modules, "apscheduler.triggers.interval", types.SimpleNamespace(IntervalTrigger=_Trigger))
    import scheduler

    logs = []
    monkeypatch.setenv("HYDRO_ENABLED", "false")
    monkeypatch.setattr(hydro_fetch, "fetch_hydro_live", _fail_network)
    monkeypatch.setitem(__import__("sys").modules, "hydro_verification", types.SimpleNamespace(verify_pending_hydro_impacts=_fail_network))
    monkeypatch.setattr(scheduler, "debug_log", lambda message: logs.append(message))

    scheduler.run_hydro_verify_job()

    assert any("Hydro deaktiviert" in message for message in logs)
    assert not any("Fehler" in message for message in logs)


def test_main_hydro_productive_run_disabled_marks_objects_without_live_request_or_error_log(monkeypatch):
    import hydro_fetch
    for name, attrs in {
        "cv2": {},
        "radar_download": {"download_kmz": lambda *a, **k: None},
        "object_tracking": {"detect_and_track_objects": lambda *a, **k: []},
        "weather_api": {"get_weather_data": lambda *a, **k: {}},
        "prediction": {"predict_positions": lambda *a, **k: []},
        "size_regressor": {},
        "kmz_export": {"save_forecast_as_kmz": lambda *a, **k: None},
        "visualize_radar": {"create_visualized_radar": lambda *a, **k: None},
        "movement_gif": {"create_movement_gif": lambda *a, **k: None},
        "upload_utilities": {"upload_file_ftp": lambda *a, **k: None},
        "fetch_700hpa_wind_per_object_slim": {"fetch_and_assign_700hpa_wind": lambda objects, *a, **k: objects},
        "assign_cape_from_forecast": {"assign_cape": lambda objects, *a, **k: objects},
        "geo_utils": {"get_roi_from_bbox": lambda *a, **k: None, "kml_bounds": lambda *a, **k: None},
        "cloud_height_from_eumetview": {"assign_cloud_top_height": lambda objects, *a, **k: objects},
        "optical_flow_features": {"assign_optical_flow_to_objects": lambda objects, *a, **k: objects},
        "fetch_arome_openmeteo": {"assign_arome_to_objects": lambda objects, *a, **k: objects},
        "fetch_synoptic_features": {"assign_synoptic_features": lambda objects, *a, **k: objects},
        "orographic_module": {"assign_orographic_scores": lambda objects, *a, **k: objects},
        "fetch_openmeteo_extended": {"assign_extended_openmeteo": lambda objects, *a, **k: objects},
        "fetch_geosphere_nowcast": {"assign_nowcast_to_objects": lambda objects, *a, **k: objects},
        "compute_convective_indices": {"assign_convective_indices": lambda objects, *a, **k: objects},
        "fetch_tawes_gust": {"fetch_tawes_stations": lambda *a, **k: [], "max_gust_near": lambda *a, **k: 0, "nearest_station_wind": lambda *a, **k: None},
        "ir_cell_detection": {"detect_ir_cells": lambda *a, **k: []},
        "ir_cell_tracking": {"mark_radar_matched_tracks": lambda *a, **k: None, "update_ir_tracking": lambda *a, **k: None},
        "climatology_features": {"enrich_objects": lambda objects, *a, **k: objects},
        "locations_check": {"annotate_locations": lambda objects, *a, **k: objects},
        "risk_watch": {"risk_watch_active": lambda *a, **k: False},
    }.items():
        monkeypatch.setitem(sys.modules, name, types.SimpleNamespace(**attrs))
    import main

    logs = []
    objects = [{"id": "cell-1", "impact": {}}]
    monkeypatch.setenv("HYDRO_ENABLED", "false")
    monkeypatch.setattr(hydro_fetch, "fetch_hydro_live", _fail_network)
    monkeypatch.setitem(__import__("sys").modules, "impact_evaluation", types.SimpleNamespace(evaluate_impact=_fail_network))
    monkeypatch.setattr(main, "debug_log", lambda message: logs.append(message), raising=False)

    main._apply_hydro_productive_run(objects, "2026-06-19_09-00-00")

    assert objects[0]["impact"]["hydro"] is False
    assert objects[0]["impact"]["hydro_status"] == "hydro_disabled"
    assert not any("HYDRO" in message and "übersprungen" in message for message in logs)


def test_api_hydro_status_disabled_is_clean_and_does_not_fetch_live(monkeypatch, tmp_path):
    import hydro_api
    import hydro_fetch

    monkeypatch.setenv("HYDRO_ENABLED", "false")
    monkeypatch.setattr(hydro_fetch, "fetch_hydro_live", _fail_network)
    monkeypatch.setattr(hydro_fetch, "load_latest_hydro_live", _fail_network)
    monkeypatch.setattr(hydro_api, "STATIC_GENERATED", tmp_path)
    monkeypatch.setattr(hydro_api, "LIVE_LATEST", tmp_path / "latest_hydro.json")
    monkeypatch.setattr(hydro_api, "LIVE_STATUS", tmp_path / "hydro_status.json")
    monkeypatch.setattr(hydro_api, "IMPACT_DIR", tmp_path)
    monkeypatch.setattr(hydro_api, "LATEST_IMPACTS", tmp_path / "latest_hydro_impacts.json")
    monkeypatch.setattr(hydro_api, "VERIFICATIONS", tmp_path / "hydro_verifications.jsonl")

    data = hydro_api.status()

    assert data["status"] == "hydro_disabled"
    assert data["enabled"] is False
    assert data["hydro_enabled"] is False
    assert data["last_error"] is None
