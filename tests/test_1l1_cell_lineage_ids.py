import importlib
import json
import sys
import zipfile
from pathlib import Path


def _lineage(monkeypatch, tmp_path):
    import runtime_config
    sys.modules.pop("cell_lineage", None)
    monkeypatch.setattr(runtime_config, "get", lambda name, default=None: {
        "CELL_LINEAGE_STATE_DIR": str(tmp_path / "cell_lineage"),
        "CELL_LINEAGE_STATE_FILE": "cell_lineage_state.json",
        "CELL_LINEAGE_EVENTS_FILE": "cell_lineage_events.jsonl",
        "CELL_ID_PREFIX": "WX",
    }.get(name, default))
    import cell_lineage
    return cell_lineage


def test_make_cell_id_uses_date_and_counter(monkeypatch, tmp_path):
    mod = _lineage(monkeypatch, tmp_path)
    state = {"version": 1, "date_counters": {}, "ir_to_cell": {}, "radar_to_cell": {}, "cells": {}}
    assert mod.make_cell_id("2026-06-18_08-15-00", state) == "WX-20260618-0001"
    assert mod.make_cell_id("2026-06-18_08-15-00", state) == "WX-20260618-0002"


def test_ensure_ir_track_gets_stable_cell_id(monkeypatch, tmp_path):
    mod = _lineage(monkeypatch, tmp_path)
    track, state = mod.ensure_ir_track_cell_id({"ir_id": "ir_17", "status": "ir_precursor"}, timestamp="2026-06-18_08-15-00", state=mod.load_lineage_state())
    assert track["cell_id"].startswith("WX-20260618-")
    assert track["ir_track_id"] == "ir_17"
    assert state["ir_to_cell"]["ir_17"] == track["cell_id"]
    again, _ = mod.ensure_ir_track_cell_id({"ir_id": "ir_17", "status": "ir_precursor"}, timestamp="2026-06-18_08-30-00", state=state)
    assert again["cell_id"] == track["cell_id"]


def test_existing_cell_id_is_preserved(monkeypatch, tmp_path):
    mod = _lineage(monkeypatch, tmp_path)
    track, _ = mod.ensure_ir_track_cell_id({"ir_id": "ir_1", "cell_id": "WX-20260618-0099"}, timestamp="2026-06-18_08-15-00", state=mod.load_lineage_state())
    assert track["cell_id"] == "WX-20260618-0099"


def test_old_ir_state_is_migrated_with_cell_id(monkeypatch, tmp_path):
    mod = _lineage(monkeypatch, tmp_path)
    import ir_cell_tracking
    importlib.reload(ir_cell_tracking)
    state_file = tmp_path / "ir_track_state.json"
    state_file.write_text(json.dumps({"tracks": {"ir_17": {"ir_id": "ir_17", "missing": 0, "ir_only_precursor": 1.0}}, "next_id": 18}), encoding="utf-8")
    monkeypatch.setattr(ir_cell_tracking, "_STATE_FILE", str(state_file))
    tracks = ir_cell_tracking.load_active_ir_tracks()
    assert tracks[0]["cell_id"]
    assert tracks[0]["ir_track_id"] == "ir_17"
    assert tracks[0]["status"] == "ir_precursor"


def test_lineage_event_written_for_new_ir_cell(monkeypatch, tmp_path):
    mod = _lineage(monkeypatch, tmp_path)
    mod.ensure_ir_track_cell_id({"ir_id": "ir_99"}, timestamp="2026-06-18_08-15-00")
    events = (tmp_path / "cell_lineage" / "cell_lineage_events.jsonl").read_text(encoding="utf-8").splitlines()
    evt = json.loads(events[0])
    assert evt["event_type"] == "ir_cell_id_created"
    assert evt["ir_track_id"] == "ir_99"


def test_radar_matched_track_keeps_cell_id(monkeypatch, tmp_path):
    _lineage(monkeypatch, tmp_path)
    import ir_cell_tracking
    importlib.reload(ir_cell_tracking)
    track = {"ir_id": "ir_1", "cell_id": "WX-20260618-0001", "ir_only_precursor": 1.0}
    state = {"tracks": {"ir_1": track}, "next_id": 2}
    monkeypatch.setattr(ir_cell_tracking, "_load_state", lambda: state)
    monkeypatch.setattr(ir_cell_tracking, "_save_state", lambda s: None)
    ir_cell_tracking.mark_radar_matched_tracks(["ir_1"])
    assert track["cell_id"] == "WX-20260618-0001"
    assert track["status"] == "radar_confirmed"
    assert track["display_as_precursor"] is False


def test_debug_export_includes_cell_lineage_dir(tmp_path):
    import debug_export
    lineage = tmp_path / "train_data" / "cell_lineage"
    lineage.mkdir(parents=True)
    (lineage / "cell_lineage_state.json").write_text('{"version":1}', encoding="utf-8")
    zip_path, _, _ = debug_export.create_debug_export_zip(base_dir=tmp_path, save_paths={}, hours=24, now=None)
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    assert any(name.endswith("train_data/cell_lineage/cell_lineage_state.json") for name in names)
    Path(zip_path).unlink(missing_ok=True)


def test_install_sh_creates_cell_lineage_dir():
    content = Path("install.sh").read_text(encoding="utf-8")
    assert "train_data/cell_lineage" in content
