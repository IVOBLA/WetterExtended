"""
B121 — Tests für tracking_memory Persistenz und _last_cells_active_ts
       nach Service-Neustart.

Prüft:
  - save_tracking_snapshot() schreibt eine JSON-Datei
  - kf-Key wird beim Speichern ausgelassen
  - load_tracking_snapshot() lädt Zellen in tracking_memory
  - Zu alter Snapshot (> INACTIVE_CELL_TRACK_DURATION_S) wird ignoriert
  - Snapshot-Alter wird korrekt zurückgegeben
  - Numpy-Arrays im contour-Feld werden korrekt serialisiert
"""
import json
import os
import sys
import time
import types
import pytest


class _FakeArray(list):
    def tolist(self):
        return [list(row) if isinstance(row, (list, tuple)) else row for row in self]


def _install_import_stubs():
    """Stellt für Snapshot-Unit-Tests optionale Tracking-Dependencies bereit."""
    if "radar_download" not in sys.modules:
        radar_stub = types.ModuleType("radar_download")
        radar_stub.get_acquisition_timestamp = lambda *args, **kwargs: None
        sys.modules["radar_download"] = radar_stub
    if "utils" not in sys.modules:
        utils_stub = types.ModuleType("utils")
        utils_stub.generate_id = lambda *args, **kwargs: "TESTID"
        sys.modules["utils"] = utils_stub
    if "utils_weather" not in sys.modules:
        weather_stub = types.ModuleType("utils_weather")
        weather_stub.find_n_nearest_stations = lambda *args, **kwargs: []
        weather_stub.weighted_average_weather = lambda *args, **kwargs: {}
        sys.modules["utils_weather"] = weather_stub
    if "debug_utils" not in sys.modules:
        debug_stub = types.ModuleType("debug_utils")
        debug_stub.debug_log = lambda *args, **kwargs: None
        debug_stub.save_debug_image = lambda *args, **kwargs: None
        sys.modules["debug_utils"] = debug_stub
    if "geo_utils" not in sys.modules:
        geo_stub = types.ModuleType("geo_utils")
        geo_stub.pixel_to_geo = lambda *args, **kwargs: (0.0, 0.0)
        geo_stub.crop_and_upscale_to_bbox = lambda *args, **kwargs: None
        sys.modules["geo_utils"] = geo_stub
    if "cv2" not in sys.modules:
        sys.modules["cv2"] = types.ModuleType("cv2")
    if "numpy" not in sys.modules:
        numpy_stub = types.ModuleType("numpy")
        numpy_stub.int32 = int

        def _array(value, dtype=None):
            return _FakeArray(value)

        numpy_stub.array = _array
        sys.modules["numpy"] = numpy_stub
    if "filterpy" not in sys.modules:
        filterpy_stub = types.ModuleType("filterpy")
        kalman_stub = types.ModuleType("filterpy.kalman")

        class _KalmanFilter:
            pass

        kalman_stub.KalmanFilter = _KalmanFilter
        filterpy_stub.kalman = kalman_stub
        sys.modules["filterpy"] = filterpy_stub
        sys.modules["filterpy.kalman"] = kalman_stub
    if "shapely" not in sys.modules:
        shapely_stub = types.ModuleType("shapely")
        geometry_stub = types.ModuleType("shapely.geometry")
        ops_stub = types.ModuleType("shapely.ops")

        class _Polygon:
            pass

        geometry_stub.Polygon = _Polygon
        ops_stub.unary_union = lambda *args, **kwargs: None
        shapely_stub.geometry = geometry_stub
        shapely_stub.ops = ops_stub
        sys.modules["shapely"] = shapely_stub
        sys.modules["shapely.geometry"] = geometry_stub
        sys.modules["shapely.ops"] = ops_stub


_install_import_stubs()


@pytest.fixture(autouse=True)
def reset_tracking_memory(monkeypatch):
    """Setzt tracking_memory vor jedem Test zurück."""
    import object_tracking
    monkeypatch.setattr(object_tracking, "tracking_memory", {})
    yield
    monkeypatch.setattr(object_tracking, "tracking_memory", {})


@pytest.fixture()
def snap_dir(tmp_path, monkeypatch):
    """Temporäres Evaluations-Verzeichnis als Snapshot-Speicherort."""
    import object_tracking
    eval_dir = tmp_path / "evaluation"
    eval_dir.mkdir()

    # _snapshot_path() via SAVE_PATHS patchen
    import config
    original_paths = config.SAVE_PATHS.copy()
    monkeypatch.setattr(
        config, "SAVE_PATHS",
        {**original_paths, "evaluation": str(eval_dir)},
    )
    return eval_dir


# ---------------------------------------------------------------------------
# Tests: save_tracking_snapshot
# ---------------------------------------------------------------------------

def test_save_creates_file(snap_dir):
    """save_tracking_snapshot schreibt eine JSON-Datei."""
    import object_tracking
    object_tracking.tracking_memory = {
        "IL001": {"id": "IL001", "lat": 46.6, "lon": 14.0, "missing": 0}
    }
    object_tracking.save_tracking_snapshot()

    snap_file = snap_dir / "tracking_memory_snapshot.json"
    assert snap_file.exists(), "Snapshot-Datei wurde nicht erstellt"


def test_save_excludes_kf_key(snap_dir):
    """kf (KalmanFilter) wird beim Speichern ausgelassen."""
    import object_tracking

    class FakeKF:
        pass

    object_tracking.tracking_memory = {
        "IL001": {"id": "IL001", "lat": 46.6, "kf": FakeKF(), "missing": 0}
    }
    object_tracking.save_tracking_snapshot()

    snap_file = snap_dir / "tracking_memory_snapshot.json"
    content = json.loads(snap_file.read_text(encoding="utf-8"))
    assert "kf" not in content.get("IL001", {}), "kf-Key darf nicht im Snapshot sein"


def test_save_serializes_numpy_contour(snap_dir):
    """numpy-Array im contour-Feld wird als Liste gespeichert."""
    pytest.importorskip("numpy")
    import numpy as np
    import object_tracking

    contour = np.array([[10, 20], [30, 40], [50, 60]], dtype=np.int32)
    object_tracking.tracking_memory = {
        "IL001": {"id": "IL001", "contour": contour, "missing": 0}
    }
    object_tracking.save_tracking_snapshot()

    snap_file = snap_dir / "tracking_memory_snapshot.json"
    content = json.loads(snap_file.read_text(encoding="utf-8"))
    saved_contour = content["IL001"]["contour"]
    assert isinstance(saved_contour, list), "Contour muss als Liste gespeichert sein"
    assert saved_contour == [[10, 20], [30, 40], [50, 60]]


def test_save_empty_memory_creates_empty_file(snap_dir):
    """Leeres tracking_memory → {} in Datei."""
    import object_tracking
    object_tracking.tracking_memory = {}
    object_tracking.save_tracking_snapshot()

    snap_file = snap_dir / "tracking_memory_snapshot.json"
    assert snap_file.exists()
    content = json.loads(snap_file.read_text(encoding="utf-8"))
    assert content == {}


# ---------------------------------------------------------------------------
# Tests: load_tracking_snapshot
# ---------------------------------------------------------------------------

def test_load_populates_tracking_memory(snap_dir):
    """load_tracking_snapshot füllt tracking_memory aus der Datei."""
    import object_tracking

    snapshot = {
        "IL001": {"id": "IL001", "lat": 46.6, "lon": 14.0, "missing": 0, "total_active_frames": 5},
        "IL002": {"id": "IL002", "lat": 46.7, "lon": 14.2, "missing": 0, "total_active_frames": 3},
    }
    snap_file = snap_dir / "tracking_memory_snapshot.json"
    snap_file.write_text(json.dumps(snapshot), encoding="utf-8")

    object_tracking.tracking_memory = {}
    age = object_tracking.load_tracking_snapshot()

    assert "IL001" in object_tracking.tracking_memory, "IL001 muss geladen sein"
    assert "IL002" in object_tracking.tracking_memory, "IL002 muss geladen sein"
    assert age < 10.0, f"Snapshot-Alter sollte nahe 0 sein, bekommen: {age}"


def test_load_returns_inf_for_missing_file(snap_dir):
    """Keine Snapshot-Datei → float('inf') zurückgeben, tracking_memory leer."""
    import object_tracking
    object_tracking.tracking_memory = {}

    # Keine Datei schreiben
    age = object_tracking.load_tracking_snapshot()
    assert age == float("inf"), f"Erwartet inf, bekommen: {age}"
    assert object_tracking.tracking_memory == {}


def test_load_ignores_old_snapshot(snap_dir, monkeypatch):
    """Snapshot älter als INACTIVE_CELL_TRACK_DURATION_S wird ignoriert."""
    import object_tracking

    snapshot = {"IL001": {"id": "IL001", "lat": 46.6, "missing": 0}}
    snap_file = snap_dir / "tracking_memory_snapshot.json"
    snap_file.write_text(json.dumps(snapshot), encoding="utf-8")

    # Datei-mtime auf 30 min in der Vergangenheit setzen
    old_time = time.time() - 1800
    os.utime(snap_file, (old_time, old_time))

    # INACTIVE_CELL_TRACK_DURATION_S auf 20 min setzen (Standard)
    monkeypatch.setattr(
        "object_tracking._snapshot_path",
        lambda: str(snap_file),
    )
    import config
    monkeypatch.setattr(config, "INACTIVE_CELL_TRACK_DURATION_S", 1200.0)

    object_tracking.tracking_memory = {}
    age = object_tracking.load_tracking_snapshot()

    assert age == float("inf"), "Zu alter Snapshot muss ignoriert werden"
    assert object_tracking.tracking_memory == {}, "tracking_memory muss leer bleiben"


def test_load_returns_correct_age(snap_dir):
    """Snapshot-Alter wird korrekt zurückgegeben (innerhalb 3s Toleranz)."""
    import object_tracking

    snapshot = {"IL001": {"id": "IL001", "missing": 0}}
    snap_file = snap_dir / "tracking_memory_snapshot.json"
    snap_file.write_text(json.dumps(snapshot), encoding="utf-8")

    # Datei 5 Minuten alt machen
    target_age = 300.0
    past_time = time.time() - target_age
    os.utime(snap_file, (past_time, past_time))

    age = object_tracking.load_tracking_snapshot()
    assert abs(age - target_age) < 3.0, (
        f"Snapshot-Alter sollte ~{target_age}s sein, bekommen: {age:.1f}s"
    )
