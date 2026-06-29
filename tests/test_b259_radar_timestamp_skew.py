"""B259 — object_tracking: Fallback auf Systemzeit wenn ARSO-KML-Timestamp
mehr als RADAR_TIMESTAMP_MAX_SKEW_MIN Minuten älter als Systemzeit ist."""
import os
import sys
import types
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Minimale Stub-Umgebung für object_tracking ────────────────────────────────
def _stub_modules(monkeypatch):
    # Import-Abhängigkeiten, die für den getesteten Timestamp-Zweig nicht benötigt werden.
    requests_stub = types.ModuleType("requests")
    requests_stub.get = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "requests", requests_stub)

    radar_download_stub = types.ModuleType("radar_download")
    radar_download_stub.get_acquisition_timestamp = lambda: None
    monkeypatch.setitem(sys.modules, "radar_download", radar_download_stub)

    filterpy_stub = types.ModuleType("filterpy")
    kalman_stub = types.ModuleType("filterpy.kalman")
    kalman_stub.KalmanFilter = object
    monkeypatch.setitem(sys.modules, "filterpy", filterpy_stub)
    monkeypatch.setitem(sys.modules, "filterpy.kalman", kalman_stub)

    shapely_stub = types.ModuleType("shapely")
    geom_stub = types.ModuleType("shapely.geometry")
    ops_stub = types.ModuleType("shapely.ops")
    geom_stub.Polygon = object
    ops_stub.unary_union = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "shapely", shapely_stub)
    monkeypatch.setitem(sys.modules, "shapely.geometry", geom_stub)
    monkeypatch.setitem(sys.modules, "shapely.ops", ops_stub)

    np_stub = types.ModuleType("numpy")
    np_stub.uint8 = int
    np_stub.int32 = int
    np_stub.float32 = float
    np_stub.ndarray = object
    np_stub.zeros = lambda *a, **k: []
    np_stub.ones = lambda *a, **k: []
    np_stub.array = lambda *a, **k: []
    np_stub.where = lambda *a, **k: ([], [])
    np_stub.column_stack = lambda *a, **k: []
    np_stub.argmin = lambda *a, **k: 0
    for name, attrs in [
        ("cv2",      {"CHAIN_APPROX_SIMPLE": 2, "RETR_EXTERNAL": 0,
                      "COLOR_BGR2HSV": 40, "COLOR_BGR2RGB": 4,
                      "imread": lambda *a, **k: None,
                      "cvtColor": lambda *a, **k: None,
                      "inRange": lambda *a, **k: None,
                      "findContours": lambda *a, **k: ([], None),
                      "boundingRect": lambda *a, **k: (0,0,0,0),
                      "contourArea": lambda *a, **k: 0.0}),
        ("numpy",    np_stub),
        ("pysteps",  types.SimpleNamespace()),
    ]:
        if name not in sys.modules:
            if isinstance(attrs, dict):
                m = types.ModuleType(name)
                for k, v in attrs.items():
                    setattr(m, k, v)
                monkeypatch.setitem(sys.modules, name, m)
            else:
                monkeypatch.setitem(sys.modules, name, attrs)


def _import_ot(monkeypatch, tmp_path):
    _stub_modules(monkeypatch)
    monkeypatch.delitem(sys.modules, "object_tracking", raising=False)
    try:
        import object_tracking as ot
        monkeypatch.setattr(ot, "SAVE_PATHS",
                            {"objects": str(tmp_path), "radar": str(tmp_path),
                             "evaluation": str(tmp_path)}, raising=False)
        return ot
    except Exception as exc:
        pytest.skip(f"object_tracking nicht importierbar: {exc}")


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_fresh_timestamp_kept_as_is(monkeypatch, tmp_path):
    """Wenn ARSO-Timestamp < 30 min alt ist, bleibt er unverändert."""
    ot = _import_ot(monkeypatch, tmp_path)
    now = datetime.now()
    fresh_ts = (now - timedelta(minutes=10)).strftime("%Y-%m-%d_%H-%M-%S")
    monkeypatch.setattr(ot, "get_acquisition_timestamp", lambda: fresh_ts, raising=False)
    logs = []
    monkeypatch.setattr(ot, "debug_log", logs.append, raising=False)

    png = tmp_path / "latest.png"
    png.write_bytes(b"\x89PNG\r\n")

    try:
        ot.detect_and_track_objects(str(png))
    except Exception:
        pass

    assert any(f"Aufnahme-Timestamp aus KMZ" in msg and fresh_ts in msg for msg in logs)
    assert not any("B259: ARSO-Timestamp" in msg for msg in logs)


def test_stale_timestamp_falls_back_to_now(monkeypatch, tmp_path):
    """Wenn ARSO-Timestamp > 30 min alt ist, wird Systemzeit verwendet."""
    ot = _import_ot(monkeypatch, tmp_path)
    now = datetime.now()
    stale_ts = (now - timedelta(hours=6)).strftime("%Y-%m-%d_%H-%M-%S")
    monkeypatch.setattr(ot, "get_acquisition_timestamp", lambda: stale_ts, raising=False)
    logs = []
    monkeypatch.setattr(ot, "debug_log", logs.append, raising=False)

    import config as _cfg
    import runtime_config as _rc
    monkeypatch.setattr(_cfg, "RADAR_TIMESTAMP_MAX_SKEW_MIN", 30.0, raising=False)
    monkeypatch.setattr(_rc, "get", lambda key, default=None: 30.0 if key == "RADAR_TIMESTAMP_MAX_SKEW_MIN" else default, raising=False)

    png = tmp_path / "latest.png"
    png.write_bytes(b"\x89PNG\r\n")

    before = datetime.now()
    try:
        ot.detect_and_track_objects(str(png))
    except Exception:
        pass
    after = datetime.now()

    assert any("B259: ARSO-Timestamp" in msg and stale_ts in msg for msg in logs)
    info_logs = [msg for msg in logs if "Aufnahme-Timestamp aus KMZ" in msg]
    assert info_logs
    saved_ts = info_logs[-1].rsplit(": ", 1)[-1]
    saved_dt = datetime.strptime(saved_ts, "%Y-%m-%d_%H-%M-%S")
    assert before - timedelta(seconds=1) <= saved_dt <= after + timedelta(seconds=1)


def test_skew_zero_disables_check(monkeypatch, tmp_path):
    """RADAR_TIMESTAMP_MAX_SKEW_MIN=0 deaktiviert den Check vollständig."""
    ot = _import_ot(monkeypatch, tmp_path)
    import config as _cfg
    import runtime_config as _rc
    monkeypatch.setattr(_cfg, "RADAR_TIMESTAMP_MAX_SKEW_MIN", 0.0, raising=False)
    monkeypatch.setattr(_rc, "get", lambda key, default=None: 0.0 if key == "RADAR_TIMESTAMP_MAX_SKEW_MIN" else default, raising=False)

    now = datetime.now()
    stale_ts = (now - timedelta(hours=12)).strftime("%Y-%m-%d_%H-%M-%S")
    monkeypatch.setattr(ot, "get_acquisition_timestamp", lambda: stale_ts, raising=False)
    logs = []
    monkeypatch.setattr(ot, "debug_log", logs.append, raising=False)

    png = tmp_path / "latest.png"
    png.write_bytes(b"\x89PNG\r\n")
    try:
        ot.detect_and_track_objects(str(png))
    except Exception:
        pass

    assert any(f"Aufnahme-Timestamp aus KMZ" in msg and stale_ts in msg for msg in logs)
    assert not any("B259: ARSO-Timestamp" in msg for msg in logs)


def test_config_parameter_exists():
    """RADAR_TIMESTAMP_MAX_SKEW_MIN muss in config.py definiert sein."""
    import config as _cfg
    val = getattr(_cfg, "RADAR_TIMESTAMP_MAX_SKEW_MIN", None)
    assert val is not None, "RADAR_TIMESTAMP_MAX_SKEW_MIN fehlt in config.py"
    assert float(val) == 30.0, f"Default-Wert sollte 30.0 sein, ist {val}"
