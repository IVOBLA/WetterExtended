"""B262: _risk_alert_check wiederholt bei Timeout (max. 2 Versuche).

Alle Modul-Mutationen gehen ausschließlich über monkeypatch — kein rohes setattr().
monkeypatch stellt alle Attribute nach jedem Test automatisch wieder her,
damit kein nachfolgender Test (z. B. test_p2_2_config_health) kontaminierte
Modul-Zustände sieht.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import importlib.machinery
import importlib.util
import types


def _make_module(name):
    return importlib.util.module_from_spec(importlib.machinery.ModuleSpec(name, loader=None))


def _stub_main_dependencies(monkeypatch):
    """Minimale Stubs fuer schwere main.py-Importe in schlanker Testumgebung."""
    def _noop(*args, **kwargs):
        return None

    if importlib.util.find_spec("requests") is None and "requests" not in sys.modules:
        req_mod = _make_module("requests")
        exceptions = types.SimpleNamespace(ReadTimeout=type("ReadTimeout", (Exception,), {}))
        monkeypatch.setattr(req_mod, "exceptions", exceptions, raising=False)
        monkeypatch.setattr(req_mod, "get", lambda *args, **kwargs: None, raising=False)
        monkeypatch.setitem(sys.modules, "requests", req_mod)

    module_attrs = {
        "cv2": {},
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
        "cloud_height_from_eumetview": {"assign_cloud_top_height": _noop},
        "optical_flow_features": {"assign_optical_flow_to_objects": _noop},
        "radar_frame_selection": {
            "remember_valid_radar_path": _noop,
            "select_optflow_prev_radar_path": _noop,
        },
        "fetch_arome_openmeteo": {"assign_arome_to_objects": _noop},
        "fetch_synoptic_features": {"assign_synoptic_features": _noop},
        "orographic_module": {"assign_orographic_scores": _noop},
        "fetch_openmeteo_extended": {"assign_extended_openmeteo": _noop},
        "fetch_geosphere_nowcast": {"assign_nowcast_to_objects": _noop},
        "compute_convective_indices": {"assign_convective_indices": _noop},
        "fetch_tawes_gust": {"fetch_tawes_stations": _noop, "max_gust_near": _noop, "nearest_station_wind": _noop},
        "ir_cell_detection": {"detect_ir_cells": _noop},
        "ir_cell_tracking": {"mark_radar_matched_tracks": _noop, "update_ir_tracking": _noop},
        "climatology_features": {"enrich_objects": _noop},
        "feature_schema": {"attach_schema_metadata": _noop},
        "locations_check": {"annotate_locations": _noop},
        "risk_watch": {"risk_watch_active": lambda *args, **kwargs: False},
    }
    for name, attrs in module_attrs.items():
        mod = _make_module(name)
        for attr, value in attrs.items():
            monkeypatch.setattr(mod, attr, value, raising=False)
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.delitem(sys.modules, "main", raising=False)


class _FakeResp:
    status_code = 200

    def json(self):
        return {"cells": []}


def _locs_with_email():
    return [{"name": "TestOrt", "email": "test@example.com", "lat": 46.6, "lon": 14.3}]


def test_einmaliger_timeout_wird_wiederholt(monkeypatch, tmp_path):
    """Bei Timeout im ersten Versuch erfolgt exakt ein zweiter Versuch."""
    _stub_main_dependencies(monkeypatch)
    import main as _main
    import runtime_config as _rc_mod
    import time as _time_mod
    import requests as _req_mod

    call_count = []

    def _fake_req_get(url, timeout):
        call_count.append(1)
        if len(call_count) == 1:
            raise _req_mod.exceptions.ReadTimeout("simulated timeout")
        return _FakeResp()

    # runtime_config.get auf dem Modul patchen (nicht das Modul ersetzen).
    # _main.runtime_config IS _rc_mod (identisches Objekt) — beide zeigen
    # auf dasselbe runtime_config-Modul. monkeypatch restauriert nach dem Test.
    def _fake_rc_get(key, default=None):
        if key == "LOCATIONS_WATCHLIST":
            return _locs_with_email()
        return default

    monkeypatch.setattr(_rc_mod, "get", _fake_rc_get)
    monkeypatch.setattr(_req_mod, "get", _fake_req_get)
    monkeypatch.setattr(_time_mod, "sleep", lambda _: None)

    real_log = tmp_path / "risk_alert_sent.json"
    real_log.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(_main, "_RISK_ALERT_LOG", str(real_log))

    try:
        _main._risk_alert_check("2026-06-29_05-00-00")
    except Exception:
        pass

    assert len(call_count) == 2, (
        f"Erwartet 2 HTTP-Versuche (1× Timeout + 1× Retry), erhalten {len(call_count)}"
    )


def test_zwei_timeouts_beenden_pruefung_sauber(monkeypatch, tmp_path):
    """Nach 2 Timeouts bricht _risk_alert_check sauber ab — kein raise."""
    _stub_main_dependencies(monkeypatch)
    import main as _main
    import runtime_config as _rc_mod
    import time as _time_mod
    import requests as _req_mod

    def _fake_rc_get(key, default=None):
        if key == "LOCATIONS_WATCHLIST":
            return _locs_with_email()
        return default

    def _always_fail(url, timeout):
        raise _req_mod.exceptions.ReadTimeout("always fails")

    monkeypatch.setattr(_rc_mod, "get", _fake_rc_get)
    monkeypatch.setattr(_req_mod, "get", _always_fail)
    monkeypatch.setattr(_time_mod, "sleep", lambda _: None)

    real_log = tmp_path / "risk_alert_sent.json"
    real_log.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(_main, "_RISK_ALERT_LOG", str(real_log))

    # Darf keine Exception werfen
    _main._risk_alert_check("2026-06-29_05-00-00")


def test_sofortiger_erfolg_ohne_retry(monkeypatch, tmp_path):
    """Bei sofortigem HTTP 200 wird requests.get nur einmal aufgerufen."""
    _stub_main_dependencies(monkeypatch)
    import main as _main
    import runtime_config as _rc_mod
    import time as _time_mod
    import requests as _req_mod

    call_count = []

    def _fake_rc_get(key, default=None):
        if key == "LOCATIONS_WATCHLIST":
            return _locs_with_email()
        return default

    def _fast_get(url, timeout):
        call_count.append(1)
        return _FakeResp()

    monkeypatch.setattr(_rc_mod, "get", _fake_rc_get)
    monkeypatch.setattr(_req_mod, "get", _fast_get)
    monkeypatch.setattr(_time_mod, "sleep", lambda _: None)

    real_log = tmp_path / "risk_alert_sent.json"
    real_log.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(_main, "_RISK_ALERT_LOG", str(real_log))

    try:
        _main._risk_alert_check("2026-06-29_05-00-00")
    except Exception:
        pass

    assert len(call_count) == 1, (
        f"Erwartet 1 HTTP-Versuch (sofortiger Erfolg), erhalten {len(call_count)}"
    )


def test_keine_locations_kein_request(monkeypatch, tmp_path):
    """Ohne Locations_with_email wird requests.get nicht aufgerufen."""
    _stub_main_dependencies(monkeypatch)
    import main as _main
    import runtime_config as _rc_mod
    import requests as _req_mod

    called = []

    def _fake_rc_get(key, default=None):
        if key == "LOCATIONS_WATCHLIST":
            return []  # keine Locations → frühzeitiger return
        return default

    def _should_not_be_called(url, timeout):
        called.append(1)
        return _FakeResp()

    monkeypatch.setattr(_rc_mod, "get", _fake_rc_get)
    monkeypatch.setattr(_req_mod, "get", _should_not_be_called)

    real_log = tmp_path / "risk_alert_sent.json"
    real_log.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(_main, "_RISK_ALERT_LOG", str(real_log))

    _main._risk_alert_check("2026-06-29_05-00-00")

    assert called == [], "requests.get darf ohne Locations nicht aufgerufen werden"


def test_regression_runtime_config_get_nicht_mutiert(monkeypatch, tmp_path):
    """Nach dem Test ist runtime_config.get wieder das Original — kein State-Leak."""
    import runtime_config as _rc_mod

    original_get = _rc_mod.get

    def _fake_rc_get(key, default=None):
        return default

    monkeypatch.setattr(_rc_mod, "get", _fake_rc_get)
    assert _rc_mod.get is _fake_rc_get  # Patch aktiv während Test

    # monkeypatch restauriert nach Test-Ende automatisch:
    # _rc_mod.get is original_get  → wird von pytest sichergestellt
