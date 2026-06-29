"""B262: _risk_alert_check wiederholt bei Timeout (max. 2 Versuche)."""
import os
import sys
import unittest.mock as mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import importlib
import types

try:
    import requests
except ModuleNotFoundError:
    requests = types.ModuleType("requests")

    class _ReadTimeout(Exception):
        pass

    requests.exceptions = types.SimpleNamespace(ReadTimeout=_ReadTimeout)
    requests.get = lambda *args, **kwargs: None
    sys.modules["requests"] = requests


def _stub_main_dependencies():
    """Minimale Stubs fuer schwere main.py-Importe in schlanker Testumgebung."""
    def _noop(*args, **kwargs):
        return None

    module_attrs = {
        "cv2": {},
        "debug_utils": {"debug_log": _noop},
        "radar_download": {"download_kmz": _noop},
        "object_tracking": {"detect_and_track_objects": _noop},
        "weather_api": {"get_weather_data": _noop},
        "prediction": {"predict_positions": _noop},
        "size_regressor": {},
        "kmz_export": {"save_forecast_as_kmz": _noop},
        "visualize_radar": {"create_visualized_radar": _noop},
        "movement_gif": {"create_movement_gif": _noop},
        "upload_utilities": {"upload_file_ftp": _noop},
        "fetch_700hpa_wind_per_object_slim": {"fetch_and_assign_700hpa_wind": _noop},
        "assign_cape_from_forecast": {"assign_cape": _noop},
        "geo_utils": {"get_roi_from_bbox": _noop, "kml_bounds": _noop},
        "config": {
            "BBOX_KAERNTEN_EXTENDED": None,
            "SAVE_PATHS": {"evaluation": "train_data/evaluation"},
            "LIVE_LOOP_INTERVAL_S": 60,
            "LOOP_INTERVAL_CELLS_S": 60,
            "LOOP_INTERVAL_NO_CELLS_S": 60,
            "LOOP_INTERVAL_NACHBEOBACHTUNG_S": 60,
            "HAIL_WARN_THRESHOLD": 0,
            "STATIONARY_RISK_MARKER_THRESHOLD": 0,
            "GUST_WARN_KMH": 0,
            "HEAVY_RAIN_WARN_MM_PER_H": 0,
        },
        "cloud_height_from_eumetview": {"assign_cloud_top_height": _noop},
        "optical_flow_features": {"assign_optical_flow_to_objects": _noop},
        "radar_frame_selection": {"remember_valid_radar_path": _noop, "select_optflow_prev_radar_path": _noop},
        "fetch_arome_openmeteo": {"assign_arome_to_objects": _noop},
        "fetch_synoptic_features": {"assign_synoptic_features": _noop},
        "orographic_module": {"assign_orographic_scores": _noop},
        "fetch_openmeteo_extended": {"assign_extended_openmeteo": _noop},
        "fetch_geosphere_nowcast": {"assign_nowcast_to_objects": _noop},
        "compute_convective_indices": {"assign_convective_indices": _noop},
        "fetch_tawes_gust": {"fetch_tawes_stations": _noop, "max_gust_near": _noop},
        "ir_cell_detection": {"detect_ir_cells": _noop},
        "ir_cell_tracking": {"mark_radar_matched_tracks": _noop, "update_ir_tracking": _noop},
        "climatology_features": {"enrich_objects": _noop},
        "feature_schema": {"attach_schema_metadata": _noop},
        "runtime_config": {"get": lambda key, default=None: default},
        "locations_check": {"annotate_locations": _noop},
        "risk_watch": {"risk_watch_active": lambda *args, **kwargs: False},
    }
    for name, attrs in module_attrs.items():
        mod = sys.modules.get(name)
        if mod is None:
            mod = types.ModuleType(name)
            sys.modules[name] = mod
        for attr, value in attrs.items():
            setattr(mod, attr, value)


def _main_module():
    _stub_main_dependencies()
    sys.modules.pop("main", None)
    import main as _main
    return _main


def _load_main():
    """main.py als Modul laden ohne es auszuführen."""
    spec = importlib.util.spec_from_file_location(
        "main_b262",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    return mod, spec


def test_einmaliger_timeout_wird_wiederholt():
    """Bei einem Timeout im ersten Versuch erfolgt ein zweiter Versuch."""
    call_count = []

    class FakeResp:
        status_code = 200
        def json(self): return {"cells": []}

    def fake_get(url, timeout):
        call_count.append(1)
        if len(call_count) == 1:
            raise requests.exceptions.ReadTimeout("simulated")
        return FakeResp()

    _main = _main_module()
    with (
        mock.patch("time.sleep"),
        mock.patch.object(_main, "runtime_config",
                          {"LOCATIONS_WATCHLIST": [{"name": "X", "email": "a@b.de",
                                                     "lat": 46.6, "lon": 14.3}]}),
        mock.patch("builtins.open", mock.mock_open(read_data="{}")),
        mock.patch("os.path.exists", return_value=True),
        mock.patch("requests.get", fake_get),
    ):
        try:
            _main._risk_alert_check("2026-06-29_05-00-00")
        except Exception:
            pass

    assert len(call_count) == 2, f"Erwartet 2 Versuche, erhalten {len(call_count)}"


def test_zwei_timeouts_beenden_pruefung_sauber():
    """Nach 2 Timeouts wird abgebrochen, ohne Exception zu werfen."""
    _main = _main_module()

    def always_fail(url, timeout):
        raise requests.exceptions.ReadTimeout("always fails")

    with (
        mock.patch("time.sleep"),
        mock.patch.object(_main, "runtime_config",
                          {"LOCATIONS_WATCHLIST": [{"name": "Y", "email": "c@d.de",
                                                     "lat": 46.6, "lon": 14.3}]}),
        mock.patch("builtins.open", mock.mock_open(read_data="{}")),
        mock.patch("os.path.exists", return_value=True),
        mock.patch("requests.get", always_fail),
    ):
        # Darf keine Exception werfen
        _main._risk_alert_check("2026-06-29_05-00-00")


def test_sofortiger_erfolg_ohne_retry():
    """Bei sofortigem 200 wird nur einmal angefragt."""
    call_count = []

    class FakeResp:
        status_code = 200
        def json(self): return {"cells": []}

    def fast_get(url, timeout):
        call_count.append(1)
        return FakeResp()

    _main = _main_module()

    with (
        mock.patch("time.sleep"),
        mock.patch.object(_main, "runtime_config",
                          {"LOCATIONS_WATCHLIST": [{"name": "Z", "email": "e@f.de",
                                                     "lat": 46.6, "lon": 14.3}]}),
        mock.patch("builtins.open", mock.mock_open(read_data="{}")),
        mock.patch("os.path.exists", return_value=True),
        mock.patch("requests.get", fast_get),
    ):
        try:
            _main._risk_alert_check("2026-06-29_05-00-00")
        except Exception:
            pass

    assert len(call_count) == 1


def test_keine_locations_kein_request():
    """Ohne Locations_with_email wird requests.get nicht aufgerufen."""
    _main = _main_module()

    with (
        mock.patch.object(_main, "runtime_config", {"LOCATIONS_WATCHLIST": []}),
        mock.patch("requests.get") as mock_get,
    ):
        _main._risk_alert_check("2026-06-29_05-00-00")
        mock_get.assert_not_called()
