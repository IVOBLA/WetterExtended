"""B374: Integration der globalen Zuordnung in update_tracking_memory."""
import sys
import types

_STUB_NAMES = (
    "cv2", "numpy", "shapely", "shapely.geometry", "shapely.ops",
    "filterpy", "filterpy.kalman", "requests", "PIL", "PIL.Image",
)
_ORIGINAL_MODULES = {name: sys.modules.get(name) for name in _STUB_NAMES}


def _restore_import_stubs():
    for name, original in _ORIGINAL_MODULES.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original

try:
    import cv2  # noqa: F401
except Exception:
    sys.modules["cv2"] = types.SimpleNamespace()

try:
    import numpy  # noqa: F401
except Exception:
    class _NP(types.SimpleNamespace):
        bool_ = bool
        def array(self, *args, **kwargs):
            return args[0] if args else []
        def mean(self, values):
            return sum(values) / len(values)
        def isscalar(self, obj):
            return not isinstance(obj, (list, tuple, dict))
    sys.modules["numpy"] = _NP()

try:
    import shapely.geometry  # noqa: F401
except Exception:
    shapely_mod = types.ModuleType("shapely")
    geom_mod = types.ModuleType("shapely.geometry")
    ops_mod = types.ModuleType("shapely.ops")
    class _Polygon:
        def __init__(self, *args, **kwargs):
            self.area = 0.0
        def intersection(self, other):
            return self
        def union(self, other):
            return self
    geom_mod.Polygon = _Polygon
    ops_mod.unary_union = lambda *args, **kwargs: _Polygon()
    sys.modules["shapely"] = shapely_mod
    sys.modules["shapely.geometry"] = geom_mod
    sys.modules["shapely.ops"] = ops_mod

try:
    import filterpy.kalman  # noqa: F401
except Exception:
    filterpy_mod = types.ModuleType("filterpy")
    kalman_mod = types.ModuleType("filterpy.kalman")
    class _KalmanFilter:
        pass
    kalman_mod.KalmanFilter = _KalmanFilter
    sys.modules["filterpy"] = filterpy_mod
    sys.modules["filterpy.kalman"] = kalman_mod

# Leichte Import-Stubs für die minimalen B374-Helfer in environments ohne optionale Laufzeitdeps.
sys.modules.setdefault("requests", types.SimpleNamespace(get=lambda *a, **k: None, Session=lambda: types.SimpleNamespace()))
sys.modules.setdefault("PIL", types.ModuleType("PIL"))
sys.modules.setdefault("PIL.Image", types.SimpleNamespace())

import pytest

try:
    import object_tracking as ot
finally:
    _restore_import_stubs()


@pytest.fixture(autouse=True)
def _reset_dt(monkeypatch):
    """Testisolation via monkeypatch (Muster: test_config_override_guard.py)."""
    monkeypatch.setattr(ot, "_last_tracking_timestamp", None, raising=False)
    yield


def test_dt_first_run_defaults_to_five():
    assert ot._tracking_dt_minutes("2026-07-14_15-00-00") == pytest.approx(5.0)


def test_dt_uses_real_gap():
    ot._tracking_dt_minutes("2026-07-14_15-00-00")
    assert ot._tracking_dt_minutes("2026-07-14_15-15-00") == pytest.approx(15.0)


def test_dt_rejects_implausible_gap():
    """Ein Sprung ueber 60 min (Neustart/Luecke) faellt auf 5.0 zurueck."""
    ot._tracking_dt_minutes("2026-07-14_10-00-00")
    assert ot._tracking_dt_minutes("2026-07-14_20-00-00") == pytest.approx(5.0)


def test_dt_rejects_backwards_time():
    ot._tracking_dt_minutes("2026-07-14_15-00-00")
    assert ot._tracking_dt_minutes("2026-07-14_14-00-00") == pytest.approx(5.0)


def test_latlon_to_km_roundtrip_distance():
    """1 Grad Breite ~ 111 km."""
    x1, y1 = ot._latlon_to_km(46.6, 14.0)
    x2, y2 = ot._latlon_to_km(47.6, 14.0)
    assert abs(y2 - y1) == pytest.approx(111.32, rel=0.01)


def test_stage_functions_removed():
    """Stage-2-Pixel-Cap darf im Matching nicht mehr verwendet werden."""
    import inspect
    src = inspect.getsource(ot.update_tracking_memory)
    assert "Stage-2-Match" not in src, "Stage-2-Fallback wurde nicht entfernt"
    assert "_s1     = max(_iou1" not in src, "Stage-1-Score wurde nicht entfernt"
    assert "_assoc_result" in src, "Globale Zuordnung nicht integriert"


def test_diagnosis_written(tmp_path, monkeypatch):
    from tracking.association import AssociationResult
    monkeypatch.setattr(ot._rc, "get", lambda k, d=None: str(tmp_path) if k == "ASSOCIATION_DIAGNOSIS_DIR" else d)
    res = AssociationResult(method="hungarian")
    res.matches = {0: "A"}
    res.cost_matrix = [[0.2]]
    res.candidate_pairs = [{"detection_index": 0, "track_id": "A", "gated": False, "cost": 0.2}]
    ot._persist_association_diagnosis(res, "2026-07-14_15-00-00", 5.0)
    assert (tmp_path / "2026-07-14_15-00-00.json").exists()


def test_diagnosis_failure_does_not_raise(monkeypatch):
    from tracking.association import AssociationResult
    monkeypatch.setattr(ot._rc, "get", lambda k, d=None: "/nonexistent/readonly" if k == "ASSOCIATION_DIAGNOSIS_DIR" else d)
    ot._persist_association_diagnosis(AssociationResult(), "2026-07-14_15-00-00", 5.0)  # darf nicht werfen


def test_association_dir_exported():
    import debug_export
    src = __import__("inspect").getsource(debug_export)
    assert "train_data/association" in src, "Assoziations-Diagnose fehlt im Export"
