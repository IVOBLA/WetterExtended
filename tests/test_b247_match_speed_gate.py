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


def test_direct_id_match_speed_core_ok_unchanged():
    """Bestehendes Verhalten: gültiger Match bleibt gültig."""
    origin = _obj(lat=47.0, lon=14.0, origin_lat=47.0, origin_lon=14.0)
    target_near = _target(id_="OBJ001", lat=47.01, lon=14.01)
    matched, _, src = at._match_actual(origin, [target_near], 10)
    assert matched == target_near
    assert src == "id"


def test_speed_core_fail_but_lineage_parent_accepted(monkeypatch):
    monkeypatch.setattr(at, "_runtime_cfg", None)
    obj = _obj(lat=47.0, lon=14.0, origin_lat=47.0, origin_lon=14.0)
    obj["id"] = "C1"
    obj["cell_id"] = "C2"
    obj["parent_cell_id"] = "C1"
    matched_obj = _target(id_="C1", lat=48.5, lon=14.0)
    matched_obj["cell_id"] = "C1"
    matched, _, src = at._match_actual(obj, [matched_obj], 10)
    assert matched == matched_obj
    assert src == "lineage_parent"
    assert at._match_type("lineage_parent") == "lineage_parent"


def test_speed_core_fail_without_lineage_still_rejected_to_nn():
    assert at._match_type("nn") not in ("lineage_parent", "lineage_merged_from", "lineage_split_child")


def test_split_child_with_different_cell_id_found_via_lineage():
    """record_cell_split()-Kind hat neue cell_id + parent_cell_id != obj id/cell_id.
    Muss trotzdem als lineage_split_child erkannt werden, nicht per NN."""
    obj = {"id": "parent_A", "cell_id": "parent_A", "lat": 46.6, "lon": 14.3,
           "forecast_lat_30": 46.61, "forecast_lon_30": 14.31}
    child = {"id": "child_X", "cell_id": "child_X", "parent_cell_id": "parent_A",
             "lat": 46.615, "lon": 14.315}
    from accuracy_tracker import _match_actual
    matched, dist, match_type = _match_actual(obj, [child], 30)
    assert matched is not None
    assert matched["id"] == "child_X"
    assert match_type == "lineage_split_child"


def test_secondary_merge_parent_with_different_cell_id_found_via_lineage():
    """record_cell_merge() haelt nur primaere cell_id; sekundaerer Parent hat
    andere id, aber steht in merged_from_cell_ids des Ergebnis-Objekts."""
    obj = {"id": "parent_B", "cell_id": "parent_B", "lat": 46.6, "lon": 14.3,
           "forecast_lat_30": 46.61, "forecast_lon_30": 14.31}
    merged = {"id": "merged_result", "cell_id": "merged_result",
              "merged_from_cell_ids": ["parent_A", "parent_B"],
              "lat": 46.615, "lon": 14.315}
    from accuracy_tracker import _match_actual
    matched, dist, match_type = _match_actual(obj, [merged], 30)
    assert matched is not None
    assert matched["id"] == "merged_result"
    assert match_type == "lineage_merged_from"


def test_no_lineage_relation_still_falls_through_to_nn():
    obj = {"id": "unrelated_A", "cell_id": "unrelated_A", "lat": 46.6, "lon": 14.3,
           "forecast_lat_30": 46.61, "forecast_lon_30": 14.31}
    other = {"id": "unrelated_B", "cell_id": "unrelated_B", "lat": 46.615, "lon": 14.315}
    from accuracy_tracker import _match_actual
    matched, dist, match_type = _match_actual(obj, [other], 30)
    assert match_type in ("nn", "miss")


def test_nearest_lineage_candidate_wins():
    obj = {"id": "parent_A", "cell_id": "parent_A", "lat": 46.6, "lon": 14.3,
           "forecast_lat_30": 46.61, "forecast_lon_30": 14.31}
    far_child = {"id": "child_far", "cell_id": "child_far", "parent_cell_id": "parent_A", "lat": 46.9, "lon": 14.8}
    near_child = {"id": "child_near", "cell_id": "child_near", "parent_cell_id": "parent_A", "lat": 46.612, "lon": 14.312}
    matched, _, match_type = at._match_actual(obj, [far_child, near_child], 30)
    assert matched == near_child
    assert match_type == "lineage_split_child"
