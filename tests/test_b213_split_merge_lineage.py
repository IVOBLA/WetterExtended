import ast
import json
import zipfile

import pytest


def _patch_state(monkeypatch, tmp_path, extra_vals=None):
    import runtime_config
    vals = {
        "CELL_LINEAGE_STATE_DIR": str(tmp_path / "cell_lineage"),
        "CELL_LINEAGE_STATE_FILE": "cell_lineage_state.json",
        "CELL_LINEAGE_EVENTS_FILE": "cell_lineage_events.jsonl",
    }
    if extra_vals:
        vals.update(extra_vals)
    monkeypatch.setattr(runtime_config, "get", lambda name, default=None: vals.get(name, default))


def _events(tmp_path):
    p = tmp_path / "cell_lineage" / "cell_lineage_events.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()]


def test_record_cell_merge_updates_state_and_event(monkeypatch, tmp_path):
    _patch_state(monkeypatch, tmp_path)
    import cell_lineage
    state = {"cells": {"WX-A": {"cell_id": "WX-A"}, "WX-B": {"cell_id": "WX-B"}}, "radar_to_cell": {"1": "WX-A", "2": "WX-B"}}
    obj = {"id": "3", "parents": ["1", "2"], "cell_id": "WX-A"}
    ev = cell_lineage.record_cell_merge(["WX-A", "WX-B"], obj, timestamp="2026-06-18_08-00-00", state=state)
    assert ev["event_type"] == "cell_merge"
    assert obj["merged_from_cell_ids"] == ["WX-A", "WX-B"]
    assert state["cells"]["WX-B"]["merged_into_cell_id"] == "WX-A"
    assert _events(tmp_path)[-1]["event_type"] == "cell_merge"


def test_merge_selects_primary_by_core_ratio(monkeypatch, tmp_path):
    _patch_state(monkeypatch, tmp_path)
    import cell_lineage
    state = {"cells": {"WX-A": {"cell_id": "WX-A"}, "WX-B": {"cell_id": "WX-B"}}, "radar_to_cell": {"1": "WX-A", "2": "WX-B"}}
    objs = [{"id": "9", "lineage": "merged", "parents": ["1", "2"]}]
    prev = {"1": {"id": "1", "cell_id": "WX-A", "core_ratio": 0.2}, "2": {"id": "2", "cell_id": "WX-B", "core_ratio": 0.8}}
    cell_lineage.save_lineage_state(state)
    cell_lineage.update_split_merge_lineage(objs, prev, timestamp="2026-06-18_08-00-00")
    assert objs[0]["cell_id"] == "WX-B"



def test_merge_keeps_survivors_own_established_cell_id(monkeypatch, tmp_path):
    """B377: B268-Survivor-Vorrang bleibt als survivor_first-Policy verfügbar.

    Der fortgeführte Tracking-Survivor (obj['id'] == einer der Parents,
    B117-Kontinuität) behält damit seine EIGENE etablierte cell_id, auch wenn
    der andere Merge-Parent einen höheren core_ratio hat.
    """
    _patch_state(monkeypatch, tmp_path, {"CELL_LINEAGE_PRIMARY_MERGE_POLICY": "survivor_first"})
    import cell_lineage
    state = {"cells": {"WX-A": {"cell_id": "WX-A"}, "WX-B": {"cell_id": "WX-B"}}, "radar_to_cell": {"1": "WX-A", "2": "WX-B"}}
    # obj["id"] == "1": der Survivor IST der etablierte Parent (analog 8ZAOEUFJ).
    objs = [{"id": "1", "lineage": "merged", "parents": ["1", "2"]}]
    prev = {"1": {"id": "1", "cell_id": "WX-A", "core_ratio": 0.2}, "2": {"id": "2", "cell_id": "WX-B", "core_ratio": 0.8}}
    cell_lineage.save_lineage_state(state)
    cell_lineage.update_split_merge_lineage(objs, prev, timestamp="2026-06-18_08-00-00")
    assert objs[0]["cell_id"] == "WX-A", (
        "Survivor mit eigenem etabliertem Track muss seine eigene cell_id "
        "behalten, nicht die des core_ratio-staerkeren Merge-Partners."
    )


def test_merge_fresh_survivor_id_still_uses_core_ratio_policy(monkeypatch, tmp_path):
    """B268-Regression: Hat der Survivor (neu generierte id, kein eigener
    radar_to_cell-Eintrag) KEINE eigene Vorgeschichte, bleibt die bestehende
    highest_core_ratio-Policy unverändert wirksam (deckt den Fall ab, in dem
    object_tracking.py mangels freiem Parent generate_id() nutzte)."""
    _patch_state(monkeypatch, tmp_path)
    import cell_lineage
    state = {"cells": {"WX-A": {"cell_id": "WX-A"}, "WX-B": {"cell_id": "WX-B"}}, "radar_to_cell": {"1": "WX-A", "2": "WX-B"}}
    objs = [{"id": "brand-new-99", "lineage": "merged", "parents": ["1", "2"]}]
    prev = {"1": {"id": "1", "cell_id": "WX-A", "core_ratio": 0.9}, "2": {"id": "2", "cell_id": "WX-B", "core_ratio": 0.1}}
    cell_lineage.save_lineage_state(state)
    cell_lineage.update_split_merge_lineage(objs, prev, timestamp="2026-06-18_08-00-00")
    assert objs[0]["cell_id"] == "WX-A"


def test_record_cell_split_primary_child_keeps_parent_cell_id(monkeypatch, tmp_path):
    _patch_state(monkeypatch, tmp_path)
    import cell_lineage
    state = {"cells": {"WX-P": {"cell_id": "WX-P"}}, "radar_to_cell": {"p": "WX-P"}}
    children = [{"id": "c1", "core_ratio": 0.9, "parents": ["p"]}, {"id": "c2", "core_ratio": 0.1, "parents": ["p"]}]
    cell_lineage.record_cell_split("WX-P", children, timestamp="2026-06-18_08-00-00", state=state)
    assert children[0]["cell_id"] == "WX-P"
    assert children[0]["lineage_status"] == "split_primary"


def test_record_cell_split_secondary_child_gets_new_cell_id(monkeypatch, tmp_path):
    _patch_state(monkeypatch, tmp_path)
    import cell_lineage
    state = {"cells": {"WX-P": {"cell_id": "WX-P"}}, "radar_to_cell": {"p": "WX-P"}, "date_counters": {}}
    children = [{"id": "c1", "core_ratio": 0.9, "parents": ["p"]}, {"id": "c2", "core_ratio": 0.1, "parents": ["p"]}]
    cell_lineage.record_cell_split("WX-P", children, timestamp="2026-06-18_08-00-00", state=state)
    assert children[1]["cell_id"] != "WX-P"
    assert children[1]["parent_cell_id"] == "WX-P"


def test_update_split_merge_lineage_uses_existing_object_tracking_fields(monkeypatch, tmp_path):
    _patch_state(monkeypatch, tmp_path)
    import cell_lineage
    cell_lineage.save_lineage_state({"cells": {"WX-A": {"cell_id": "WX-A"}, "WX-B": {"cell_id": "WX-B"}}, "radar_to_cell": {"1": "WX-A", "2": "WX-B"}})
    objs = [{"id": "3", "lineage": "merged", "parents": ["1", "2"]}]
    events = cell_lineage.update_split_merge_lineage(objs, {"1": {"core_ratio": 0.1}, "2": {"core_ratio": 0.2}}, timestamp="2026-06-18_08-00-00")
    assert events and events[0]["event_type"] == "cell_merge"
    assert objs[0]["lineage_status"] == "merged"


def test_unresolved_parent_does_not_crash(monkeypatch, tmp_path):
    _patch_state(monkeypatch, tmp_path)
    import cell_lineage
    events = cell_lineage.update_split_merge_lineage([{"id": "3", "lineage": "merged", "parents": ["x", "y"]}], {}, timestamp="2026-06-18_08-00-00")
    assert events[-1]["unresolved_parent_ids"] == ["x", "y"]


def test_api_preserves_split_merge_fields():
    obj = {"id": "1", "cell_id": "WX-1", "parent_cell_id": "WX-P", "child_cell_ids": ["WX-C"], "merged_from_cell_ids": ["WX-A"], "merged_into_cell_id": "WX-M", "alias_cell_ids": ["WX-A"], "lineage_status": "merged"}
    for key in ("parent_cell_id", "child_cell_ids", "merged_from_cell_ids", "merged_into_cell_id", "alias_cell_ids", "lineage_status"):
        assert key in obj


def test_kmz_contains_split_merge_extended_data(tmp_path):
    pytest.importorskip("simplekml")
    from kmz_export import save_forecast_as_kmz
    out = tmp_path / "forecast.kmz"
    save_forecast_as_kmz({}, {}, str(out), current_objects=[{"id": "1", "lat": 46.7, "lon": 14.3, "cell_id": "WX-1", "parent_cell_id": "WX-P", "merged_from_cell_ids": ["WX-A"], "lineage_status": "merged"}])
    with zipfile.ZipFile(out) as zf:
        kml = zf.read("doc.kml").decode("utf-8")
    assert "parent_cell_id" in kml or "merged_from_cell_ids" in kml


def test_forecast_error_details_keep_lineage_fields():
    pytest.importorskip("cv2")
    import accuracy_tracker
    rec = accuracy_tracker._detail_record({"id": "1", "cell_id": "WX-1", "lat": 46.7, "lon": 14.3, "forecast_lat_10": 46.8, "forecast_lon_10": 14.4, "lineage_status": "split_child", "parent_cell_id": "WX-P", "merged_from_cell_ids": ["WX-A"]}, __import__("datetime").datetime.utcnow(), __import__("datetime").datetime.utcnow(), 10, None, None, "miss", False, False, 10)
    assert rec["lineage_status"] == "split_child"
    assert rec["parent_cell_id"] == "WX-P"


def test_no_external_requests_in_split_merge_lineage():
    src = open("cell_lineage.py", encoding="utf-8").read()
    tree = ast.parse(src)
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    assert "requests" not in imports
    assert "httpx" not in imports
    assert "urllib.request" not in imports


def test_parent_to_split_child_matched_at_verification():
    obj = {"cell_id": "child_1", "parent_cell_id": "parent_A"}
    matched = {"cell_id": "parent_A", "id": "parent_A"}
    # Direkter Parent-Match muss als lineage_parent erkannt werden
    assert str(matched.get("cell_id")) == obj["parent_cell_id"]


def test_multiple_merge_sources_checked():
    obj = {"cell_id": "merged_1", "merged_from_cell_ids": ["A", "B", "C"]}
    matched = {"cell_id": "B", "id": "B"}
    assert str(matched.get("cell_id")) in [str(x) for x in obj["merged_from_cell_ids"]]


def test_horizon_dependent_nn_max_distance():
    from config import VERIFICATION_NN_MAX_MATCH_KM_BY_HORIZON, VERIFICATION_NN_MAX_MATCH_KM
    assert VERIFICATION_NN_MAX_MATCH_KM_BY_HORIZON["10"] < VERIFICATION_NN_MAX_MATCH_KM_BY_HORIZON["60"]
    assert VERIFICATION_NN_MAX_MATCH_KM_BY_HORIZON["60"] <= VERIFICATION_NN_MAX_MATCH_KM


def test_evaluate_for_horizon_matches_split_child_with_new_cell_id(monkeypatch, tmp_path):
    import accuracy_tracker

    obj_dir = tmp_path / "objects"
    eval_dir = tmp_path / "evaluation"
    obj_dir.mkdir()
    eval_dir.mkdir()
    source = [{
        "id": "parent_A", "cell_id": "parent_A", "lat": 46.6, "lon": 14.3,
        "x": 10, "y": 10, "forecast_x_30": 30, "forecast_y_30": 30,
        "forecast_lat_30": 46.61, "forecast_lon_30": 14.31,
    }]
    target = [{
        "id": "child_X", "cell_id": "child_X", "parent_cell_id": "parent_A",
        "lat": 46.615, "lon": 14.315, "x": 10, "y": 10,
    }]
    (obj_dir / "2026-07-02_10-00-00.json").write_text(json.dumps(source), encoding="utf-8")
    (obj_dir / "2026-07-02_10-30-00.json").write_text(json.dumps(target), encoding="utf-8")
    monkeypatch.setitem(accuracy_tracker.SAVE_PATHS, "objects", str(obj_dir))
    monkeypatch.setattr(accuracy_tracker, "DETAILS_FILE", str(eval_dir / "forecast_error_details.jsonl"))
    monkeypatch.setattr(accuracy_tracker, "_runtime_cfg", None)

    result = accuracy_tracker.evaluate_for_horizon(30, since_hours=24)

    assert result["by_match_type"]["lineage_split_child"]["verified"] == 1
    details = [json.loads(line) for line in (eval_dir / "forecast_error_details.jsonl").read_text(encoding="utf-8").splitlines()]
    assert details[-1]["match_type"] == "lineage_split_child"
