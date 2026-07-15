"""B392: IR-Confirm darf Radar-Merge-/Split-Lineage nicht ueberschreiben."""
from pathlib import Path

import cell_lineage as cl


def _state():
    state = cl._empty_state()
    state["emitted_event_signatures"] = []
    state["emitted_event_last_seen"] = {}
    return state


def _match():
    return {
        "score": 0.91,
        "decision": "strong",
        "reason": "test",
        "centroid_distance_km": 2.0,
        "predicted_centroid_distance_km": 1.5,
    }


def test_merge_identity_status_and_event_survive_ir_confirmation(monkeypatch):
    written = []
    monkeypatch.setattr(cl, "append_lineage_event", lambda ev: written.append(dict(ev)))
    radar = {"id": "RID-M", "cell_id": "CELL-MERGE", "lineage": "merged", "lineage_status": "merged", "lineage_event": "cell_merge", "transition_event": "merge", "transition_phase": "confirmed", "transition_signature": "SIG-M", "parents": ["RID-A", "RID-B"], "merged_from_cell_ids": ["CELL-A", "CELL-B"], "alias_cell_ids": ["CELL-B"]}
    ir = {"ir_track_id": "ir_1", "ir_id": "ir_1", "cell_id": "CELL-IR", "first_seen_timestamp": "2026-07-15T09:00:00Z"}
    radar, ir, state = cl.apply_ir_radar_lineage_match(radar, ir, _match(), state=_state(), timestamp="2026-07-15T10:00:00Z")
    assert radar["cell_id"] == "CELL-MERGE"
    assert radar["lineage_status"] == "merged"
    assert radar["lineage_event"] == "cell_merge"
    assert radar["transition_event"] == "merge"
    assert radar["transition_phase"] == "confirmed"
    assert radar["transition_signature"] == "SIG-M"
    assert radar["parents"] == ["RID-A", "RID-B"]
    assert radar["merged_from_cell_ids"] == ["CELL-A", "CELL-B"]
    assert ir["cell_id"] == "CELL-MERGE"
    assert state["radar_to_cell"]["RID-M"] == "CELL-MERGE"
    assert state["ir_to_cell"]["ir_1"] == "CELL-MERGE"
    assert "CELL-IR" in radar["alias_cell_ids"]
    assert state["cells"]["CELL-IR"]["canonical_cell_id"] == "CELL-MERGE"
    assert state["cells"]["CELL-IR"]["radar_confirmed"] is True
    assert state["cells"]["CELL-IR"]["became_radar_cell"] == 1
    assert written[-1]["cell_id"] == "CELL-MERGE"
    assert written[-1]["source_ir_cell_id"] == "CELL-IR"
    assert written[-1]["preserved_structural_lineage"] is True


def test_split_primary_survives_ir_confirmation(monkeypatch):
    monkeypatch.setattr(cl, "append_lineage_event", lambda ev: None)
    radar = {"id": "RID-P", "cell_id": "CELL-PARENT", "lineage": "split", "lineage_status": "split_primary", "lineage_event": "cell_split", "transition_event": "split", "parent_cell_id": "CELL-PARENT"}
    ir = {"ir_track_id": "ir_2", "cell_id": "CELL-IR-P"}
    radar, ir, state = cl.apply_ir_radar_lineage_match(radar, ir, _match(), state=_state(), timestamp="2026-07-15T10:00:00Z")
    assert radar["cell_id"] == "CELL-PARENT"
    assert radar["lineage_status"] == "split_primary"
    assert radar["lineage_event"] == "cell_split"
    assert radar["transition_event"] == "split"
    assert radar["parent_cell_id"] == "CELL-PARENT"
    assert ir["cell_id"] == "CELL-PARENT"
    assert state["ir_to_cell"]["ir_2"] == "CELL-PARENT"


def test_split_child_survives_ir_confirmation(monkeypatch):
    monkeypatch.setattr(cl, "append_lineage_event", lambda ev: None)
    radar = {"id": "RID-C", "cell_id": "CELL-CHILD", "lineage": "split", "lineage_status": "split_child", "transition_event": "split", "split_from_cell_id": "CELL-PARENT", "parent_cell_id": "CELL-PARENT"}
    ir = {"ir_track_id": "ir_3", "cell_id": "CELL-IR-C"}
    radar, ir, state = cl.apply_ir_radar_lineage_match(radar, ir, _match(), state=_state(), timestamp="2026-07-15T10:00:00Z")
    assert radar["cell_id"] == "CELL-CHILD"
    assert radar["lineage_status"] == "split_child"
    assert radar["split_from_cell_id"] == "CELL-PARENT"
    assert radar["parent_cell_id"] == "CELL-PARENT"
    assert state["radar_to_cell"]["RID-C"] == "CELL-CHILD"
    assert state["ir_to_cell"]["ir_3"] == "CELL-CHILD"


def test_normal_radar_object_still_inherits_ir_cell_id(monkeypatch):
    monkeypatch.setattr(cl, "append_lineage_event", lambda ev: None)
    radar = {"id": "RID-N", "cell_id": "TEMP-RADAR", "lineage": "continued", "lineage_status": None, "transition_event": None}
    ir = {"ir_track_id": "ir_4", "cell_id": "CELL-IR-N"}
    radar, ir, state = cl.apply_ir_radar_lineage_match(radar, ir, _match(), state=_state(), timestamp="2026-07-15T10:00:00Z")
    assert radar["cell_id"] == "CELL-IR-N"
    assert radar["lineage_status"] == "radar_confirmed"
    assert radar["lineage_event"] == "ir_to_radar_confirmation"
    assert ir["cell_id"] == "CELL-IR-N"
    assert state["radar_to_cell"]["RID-N"] == "CELL-IR-N"
    assert state["ir_to_cell"]["ir_4"] == "CELL-IR-N"


def test_reconciled_ir_alias_cannot_become_negative_label(monkeypatch):
    monkeypatch.setattr(cl, "append_lineage_event", lambda ev: None)
    monkeypatch.setattr(cl, "append_ir_lead_time_label", lambda label: None)
    monkeypatch.setattr(cl, "load_existing_lead_time_label_keys", lambda: set())
    state = _state()
    state["cells"]["CELL-IR"] = {"cell_id": "CELL-IR", "first_seen_timestamp": "2026-07-15T00:00:00Z", "last_seen_timestamp": "2026-07-15T00:10:00Z", "status": "ir_precursor"}
    radar = {"id": "RID-X", "cell_id": "CELL-X", "lineage_status": "merged", "transition_event": "merge"}
    ir = {"ir_track_id": "ir_5", "cell_id": "CELL-IR", "first_seen_timestamp": "2026-07-15T00:00:00Z"}
    _, ir, state = cl.apply_ir_radar_lineage_match(radar, ir, _match(), state=state, timestamp="2026-07-15T00:15:00Z")
    negatives = cl.finalize_expired_ir_precursors(timestamp="2026-07-16T12:00:00Z", active_ir_tracks=[], state=state)
    assert negatives == []


def test_event_object_and_mappings_use_one_cell_id(monkeypatch):
    written = []
    monkeypatch.setattr(cl, "append_lineage_event", lambda ev: written.append(dict(ev)))
    radar = {"id": "RID-Z", "cell_id": "CELL-Z", "lineage_status": "merged", "transition_event": "merge"}
    ir = {"ir_track_id": "ir_6", "cell_id": "CELL-OLD-IR"}
    radar, ir, state = cl.apply_ir_radar_lineage_match(radar, ir, _match(), state=_state(), timestamp="2026-07-15T10:00:00Z")
    resolved = radar["cell_id"]
    assert resolved == ir["cell_id"]
    assert resolved == state["radar_to_cell"]["RID-Z"]
    assert resolved == state["ir_to_cell"]["ir_6"]
    assert resolved == written[-1]["cell_id"]


def test_main_keeps_radar_lineage_before_ir_and_guards_legacy_fallback():
    src = Path("main.py").read_text(encoding="utf-8")
    radar_pos = src.index("_radar_lineage_events = update_split_merge_lineage(")
    ir_pos = src.index("_score_match_ir_radar_lineage(", radar_pos)
    assert radar_pos < ir_pos, "B386 wurde rueckgaengig gemacht"
    assert "resolve_ir_radar_cell_id" in src
    assert "_resolved_cell_id = resolve_ir_radar_cell_id(obj, best_ir)" in src
