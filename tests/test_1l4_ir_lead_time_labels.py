import importlib
import json
import sys
from pathlib import Path

import pytest


def _mod(monkeypatch, tmp_path):
    sys.modules.pop("cell_lineage", None)
    import runtime_config
    overrides = {
        "CELL_LINEAGE_STATE_DIR": str(tmp_path / "cell_lineage"),
        "CELL_LINEAGE_STATE_FILE": "cell_lineage_state.json",
        "CELL_LINEAGE_EVENTS_FILE": "cell_lineage_events.jsonl",
        "IR_LEAD_TIME_LABELS_FILE": "ir_lead_time_labels.jsonl",
        "IR_RADAR_MATCH_SCORE_MIN": 0.1,
        "IR_RADAR_MATCH_SCORE_WEAK_MIN": 0.05,
    }
    monkeypatch.setattr(runtime_config, "get", lambda k, d=None: overrides.get(k, d))
    import cell_lineage
    return cell_lineage


def _rows(path: Path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _ir(**kw):
    d = {"ir_track_id": "ir_17", "lat": 46.6, "lon": 14.3, "first_seen_timestamp": "2026-06-18_08-15-00", "last_seen_timestamp": "2026-06-18_08-20-00", "bt_min_k": 214.8, "bt_trend_k_per_min": -0.8, "cloud_height_m": 11800.0, "area_growth_km2_per_min": 4.5}
    d.update(kw)
    return d


def _radar(**kw):
    d = {"id": "42", "lat": 46.6, "lon": 14.3, "area_px": 350, "intensity_label": "strong"}
    d.update(kw)
    return d


def test_compute_lead_time_min(monkeypatch, tmp_path):
    mod = _mod(monkeypatch, tmp_path)
    assert mod.compute_lead_time_min("2026-06-18_08-15-00", "2026-06-18_08-35-00") == 20.0


def test_positive_label_written_on_ir_to_radar_confirmation(monkeypatch, tmp_path):
    mod = _mod(monkeypatch, tmp_path)
    state = mod._empty_state()
    ir, state = mod.ensure_ir_track_cell_id(_ir(), timestamp="2026-06-18_08-20-00", state=state)
    event = {"event_type": "ir_to_radar_confirmation", "cell_id": ir["cell_id"], "timestamp": "2026-06-18_08-35-00", "score": 0.82, "decision": "strong", "reason": "score_ge_min"}
    label = mod.maybe_write_positive_ir_lead_time_label(ir["cell_id"], ir_track=ir, radar_obj=_radar(cell_id=ir["cell_id"]), event=event, state=state)
    assert label["became_radar_cell"] == 1
    assert label["ended_without_radar"] == 0
    assert label["lead_time_min"] == 20.0
    assert _rows(tmp_path / "cell_lineage" / "ir_lead_time_labels.jsonl")[0]["cell_id"] == ir["cell_id"]


def test_positive_label_contains_ir_growth_features(monkeypatch, tmp_path):
    mod = _mod(monkeypatch, tmp_path)
    state = mod._empty_state()
    ir, state = mod.ensure_ir_track_cell_id(_ir(), state=state)
    label = mod.maybe_write_positive_ir_lead_time_label(ir["cell_id"], ir_track=ir, radar_obj=_radar(cell_id=ir["cell_id"]), event={"timestamp": "2026-06-18_08-35-00"}, state=state)
    for key in ("bt_min_k", "bt_trend_k_per_min", "cloud_height_m", "area_growth_km2_per_min"):
        assert label[key] == ir[key]


def test_positive_label_dedup_by_cell_id(monkeypatch, tmp_path):
    mod = _mod(monkeypatch, tmp_path)
    state = mod._empty_state(); ir, state = mod.ensure_ir_track_cell_id(_ir(), state=state)
    ev = {"timestamp": "2026-06-18_08-35-00"}
    mod.maybe_write_positive_ir_lead_time_label(ir["cell_id"], ir_track=ir, radar_obj=_radar(cell_id=ir["cell_id"]), event=ev, state=state)
    mod.maybe_write_positive_ir_lead_time_label(ir["cell_id"], ir_track=ir, radar_obj=_radar(cell_id=ir["cell_id"]), event=ev, state=state)
    assert len(_rows(tmp_path / "cell_lineage" / "ir_lead_time_labels.jsonl")) == 1


def test_negative_label_written_for_expired_ir_precursor(monkeypatch, tmp_path):
    mod = _mod(monkeypatch, tmp_path)
    state = mod._empty_state(); ir, state = mod.ensure_ir_track_cell_id(_ir(last_seen_timestamp="2026-06-18_08-20-00"), timestamp="2026-06-18_08-20-00", state=state)
    labels = mod.finalize_expired_ir_precursors(timestamp="2026-06-18_10-00-00", active_ir_tracks=[], state=state)
    assert labels and labels[0]["became_radar_cell"] == 0
    assert labels[0]["ended_without_radar"] == 1
    assert labels[0]["negative_reason"] == "expired_without_radar"


def test_no_negative_label_for_radar_confirmed_cell(monkeypatch, tmp_path):
    mod = _mod(monkeypatch, tmp_path)
    state = mod._empty_state(); ir, state = mod.ensure_ir_track_cell_id(_ir(), timestamp="2026-06-18_08-20-00", state=state)
    state["cells"][ir["cell_id"]]["radar_confirmed"] = True
    assert mod.finalize_expired_ir_precursors(timestamp="2026-06-18_10-00-00", active_ir_tracks=[], state=state) == []


def test_no_negative_label_before_min_final_age(monkeypatch, tmp_path):
    mod = _mod(monkeypatch, tmp_path)
    state = mod._empty_state(); mod.ensure_ir_track_cell_id(_ir(last_seen_timestamp="2026-06-18_09-50-00"), timestamp="2026-06-18_09-50-00", state=state)
    assert mod.finalize_expired_ir_precursors(timestamp="2026-06-18_10-00-00", active_ir_tracks=[], state=state) == []


def test_late_positive_after_negative_marks_supersedes(monkeypatch, tmp_path):
    mod = _mod(monkeypatch, tmp_path)
    state = mod._empty_state(); ir, state = mod.ensure_ir_track_cell_id(_ir(), timestamp="2026-06-18_08-20-00", state=state)
    mod.finalize_expired_ir_precursors(timestamp="2026-06-18_10-00-00", active_ir_tracks=[], state=state)
    label = mod.maybe_write_positive_ir_lead_time_label(ir["cell_id"], ir_track=ir, radar_obj=_radar(cell_id=ir["cell_id"]), event={"timestamp": "2026-06-18_10-05-00"}, state=state)
    assert label["became_radar_cell"] == 1
    assert label.get("supersedes_negative") is True


def test_update_cell_lineage_returns_label_events(monkeypatch, tmp_path):
    mod = _mod(monkeypatch, tmp_path)
    _, _, events = mod.update_cell_lineage([_radar()], [_ir()], timestamp="2026-06-18_08-35-00")
    assert any(e.get("event_type") == "ir_lead_time_label_written" for e in events)


def test_api_lead_time_labels_missing_file(monkeypatch, tmp_path):
    mod = _mod(monkeypatch, tmp_path)
    pytest.importorskip("flask")
    import app
    app.app.config["TESTING"] = True
    with app.app.test_client() as c:
        resp = c.get("/api/cell_lineage/lead_time_labels")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "missing"


def test_api_lead_time_labels_summary(monkeypatch, tmp_path):
    mod = _mod(monkeypatch, tmp_path)
    p = mod.labels_path(); p.parent.mkdir(parents=True)
    p.write_text('\n'.join([
        json.dumps({"cell_id":"a","became_radar_cell":1,"ended_without_radar":0,"lead_time_min":10}),
        json.dumps({"cell_id":"b","became_radar_cell":1,"ended_without_radar":0,"lead_time_min":30}),
        json.dumps({"cell_id":"c","became_radar_cell":0,"ended_without_radar":1}),
    ]), encoding="utf-8")
    pytest.importorskip("flask")
    import app
    app.app.config["TESTING"] = True
    with app.app.test_client() as c:
        data = c.get("/api/cell_lineage/lead_time_labels").get_json()
    assert data["status"] == "ok"
    assert data["positive_count"] == 2
    assert data["negative_count"] == 1
    assert data["median_lead_time_min"] == 20.0


def test_debug_export_includes_ir_lead_time_labels(tmp_path):
    import debug_export
    p = tmp_path / "train_data" / "cell_lineage"; p.mkdir(parents=True)
    (p / "ir_lead_time_labels.jsonl").write_text('{"cell_id":"x"}\n', encoding="utf-8")
    z, _, _ = debug_export.create_debug_export_zip(base_dir=tmp_path, save_paths={}, now=None)
    import zipfile
    with zipfile.ZipFile(z) as zz:
        assert any(n.endswith("train_data/cell_lineage/ir_lead_time_labels.jsonl") for n in zz.namelist())


def test_cleanup_does_not_remove_lead_time_labels_by_default(monkeypatch, tmp_path):
    p = tmp_path / "train_data" / "cell_lineage"; p.mkdir(parents=True)
    label = p / "ir_lead_time_labels.jsonl"; label.write_text("{}\n", encoding="utf-8")
    # Schutz: Lineage ist standardmäßig nicht in config.DATA_CLEANUP_PATHS enthalten.
    import config
    assert "train_data/cell_lineage/" not in config.DATA_CLEANUP_PATHS
    assert label.exists()
