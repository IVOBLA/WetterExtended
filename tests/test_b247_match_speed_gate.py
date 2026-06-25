"""B247 — Verifikations-Matching: Speed-Gate + Core-Anforderung."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import accuracy_tracker as at


def _obj(lat=47.0, lon=14.0, core_ratio=0.5, origin_lat=None, origin_lon=None):
    return {
        "id": "OBJ001",
        "lat": lat,
        "lon": lon,
        "core_ratio": core_ratio,
        "origin_lat": origin_lat if origin_lat is not None else lat,
        "origin_lon": origin_lon if origin_lon is not None else lon,
        "forecast_lat_10": lat + 0.01,
        "forecast_lon_10": lon + 0.01,
    }


def _target(id_="OBJ001", lat=47.0, lon=14.0, core_ratio=0.5):
    return {"id": id_, "lat": lat, "lon": lon, "core_ratio": core_ratio}


def test_speed_gate_rejects_ghost_match(monkeypatch):
    monkeypatch.setattr(at, "_runtime_cfg", None)
    origin = _obj(lat=47.0, lon=14.0, origin_lat=47.0, origin_lon=14.0)
    target_far = _target(id_="OBJ001", lat=48.5, lon=14.0)
    matched, dist, src = at._match_actual(origin, [target_far], 10)
    assert matched is None or src == "miss", f"Ghost-Match nicht verworfen: src={src}, dist={dist:.1f}"


def test_speed_gate_accepts_plausible_match(monkeypatch):
    monkeypatch.setattr(at, "_runtime_cfg", None)
    origin = _obj(lat=47.0, lon=14.0, origin_lat=47.0, origin_lon=14.0)
    target_near = _target(id_="OBJ001", lat=47.045, lon=14.0)
    matched, dist, src = at._match_actual(origin, [target_near], 10)
    assert matched is not None, f"Plausibler Match wurde verworfen: dist={dist:.1f}"
    assert src == "id", f"Falscher Match-Typ: {src}"


def test_speed_gate_zero_disables(monkeypatch):
    class _Cfg:
        @staticmethod
        def get(name, default=None):
            if name == "VERIFICATION_MATCH_MAX_ACTUAL_SPEED_KMH":
                return 0.0
            if name == "VERIFICATION_CORE_MIN_RATIO":
                return 0.0
            return default
    monkeypatch.setattr(at, "_runtime_cfg", _Cfg())
    origin = _obj(lat=47.0, lon=14.0, origin_lat=47.0, origin_lon=14.0)
    target_far = _target(id_="OBJ001", lat=48.5, lon=14.0)
    assert at._match_valid_b247(origin, target_far, 10) is True


def test_core_gate_rejects_stratiform_actual(monkeypatch):
    class _Cfg:
        @staticmethod
        def get(name, default=None):
            if name == "VERIFICATION_MATCH_MAX_ACTUAL_SPEED_KMH":
                return 0.0
            if name == "VERIFICATION_CORE_MIN_RATIO":
                return 0.05
            return default
    monkeypatch.setattr(at, "_runtime_cfg", _Cfg())
    origin = _obj(core_ratio=0.6, origin_lat=47.0, origin_lon=14.0)
    stratiform_target = _target(id_="OBJ001", lat=47.0, lon=14.0, core_ratio=0.0)
    assert at._match_valid_b247(origin, stratiform_target, 10) is False


def test_core_gate_accepts_convective_actual(monkeypatch):
    class _Cfg:
        @staticmethod
        def get(name, default=None):
            if name == "VERIFICATION_MATCH_MAX_ACTUAL_SPEED_KMH":
                return 0.0
            if name == "VERIFICATION_CORE_MIN_RATIO":
                return 0.05
            return default
    monkeypatch.setattr(at, "_runtime_cfg", _Cfg())
    origin = _obj(core_ratio=0.6, origin_lat=47.0, origin_lon=14.0)
    conv_target = _target(id_="OBJ001", lat=47.0, lon=14.0, core_ratio=0.3)
    assert at._match_valid_b247(origin, conv_target, 10) is True


def test_core_gate_inactive_for_stratiform_origin(monkeypatch):
    class _Cfg:
        @staticmethod
        def get(name, default=None):
            if name == "VERIFICATION_MATCH_MAX_ACTUAL_SPEED_KMH":
                return 0.0
            if name == "VERIFICATION_CORE_MIN_RATIO":
                return 0.05
            return default
    monkeypatch.setattr(at, "_runtime_cfg", _Cfg())
    stratiform_origin = _obj(core_ratio=0.0, origin_lat=47.0, origin_lon=14.0)
    stratiform_target = _target(id_="OBJ001", lat=47.0, lon=14.0, core_ratio=0.0)
    assert at._match_valid_b247(stratiform_origin, stratiform_target, 10) is True


def test_core_gate_disabled_when_zero(monkeypatch):
    monkeypatch.setattr(at, "_runtime_cfg", None)
    origin = _obj(core_ratio=0.9, origin_lat=47.0, origin_lon=14.0)
    stratiform_target = _target(id_="OBJ001", lat=47.0, lon=14.0, core_ratio=0.0)
    assert at._match_valid_b247(origin, stratiform_target, 10) is True


def test_fallback_to_nn_when_id_match_rejected(monkeypatch):
    monkeypatch.setattr(at, "_runtime_cfg", None)
    origin = _obj(lat=47.0, lon=14.0, origin_lat=47.0, origin_lon=14.0)
    rejected_id = _target(id_="OBJ001", lat=48.5, lon=14.0)
    nn_target = _target(id_="OBJ002", lat=47.01, lon=14.01)
    matched, _, src = at._match_actual(origin, [rejected_id, nn_target], 10)
    assert matched == nn_target
    assert src == "nn"


def test_max_actual_speed_runtime_override(monkeypatch):
    class _Cfg:
        @staticmethod
        def get(name, default=None):
            return 200.0 if name == "VERIFICATION_MATCH_MAX_ACTUAL_SPEED_KMH" else default
    monkeypatch.setattr(at, "_runtime_cfg", _Cfg())
    assert at._max_actual_speed_kmh() == 200.0


def test_core_min_ratio_runtime_override(monkeypatch):
    class _Cfg:
        @staticmethod
        def get(name, default=None):
            return 0.1 if name == "VERIFICATION_CORE_MIN_RATIO" else default
    monkeypatch.setattr(at, "_runtime_cfg", _Cfg())
    assert at._core_min_ratio() == 0.1


def test_defaults_from_config(monkeypatch):
    monkeypatch.setattr(at, "_runtime_cfg", None)
    from config import VERIFICATION_MATCH_MAX_ACTUAL_SPEED_KMH, VERIFICATION_CORE_MIN_RATIO
    assert at._max_actual_speed_kmh() == float(VERIFICATION_MATCH_MAX_ACTUAL_SPEED_KMH)
    assert at._core_min_ratio() == float(VERIFICATION_CORE_MIN_RATIO)
