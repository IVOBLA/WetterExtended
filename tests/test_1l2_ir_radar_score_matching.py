import importlib
import json
import sys
from pathlib import Path


def _lineage(monkeypatch, tmp_path):
    import runtime_config
    sys.modules.pop("cell_lineage", None)
    vals = {
        "CELL_LINEAGE_STATE_DIR": str(tmp_path / "cell_lineage"),
        "CELL_LINEAGE_STATE_FILE": "cell_lineage_state.json",
        "CELL_LINEAGE_EVENTS_FILE": "cell_lineage_events.jsonl",
        "CELL_ID_PREFIX": "WX",
    }
    monkeypatch.setattr(runtime_config, "get", lambda name, default=None: vals.get(name, default))
    import cell_lineage
    return cell_lineage


def _radar(**kw):
    d = {"id": "42", "lat": 46.7, "lon": 14.0, "core_ratio": 0.5, "area": 20, "vx_deg_min": 0.01, "vy_deg_min": 0.0}
    d.update(kw)
    return d


def _ir(**kw):
    d = {"ir_id": "ir_17", "ir_track_id": "ir_17", "cell_id": "WX-20260618-0001", "lat": 46.7, "lon": 14.02, "last_seen_timestamp": "2026-06-18_08-05-00", "vx_deg_min": 0.01, "vy_deg_min": 0.0}
    d.update(kw)
    return d


def test_score_rejects_far_ir_track(monkeypatch, tmp_path):
    mod = _lineage(monkeypatch, tmp_path)
    m = mod.compute_ir_radar_match_score(_radar(), _ir(lat=47.5, lon=15.0), timestamp="2026-06-18_08-10-00")
    assert m["matched"] is False
    assert m["reason"] == "distance_too_far"


def test_score_accepts_close_fresh_growing_ir_track(monkeypatch, tmp_path):
    mod = _lineage(monkeypatch, tmp_path)
    m = mod.compute_ir_radar_match_score(_radar(cape=1800), _ir(bt_trend_k_per_min=-0.8, cloud_height_trend_m_per_min=100, area_growth_km2_per_min=2, overshooting_top=True), timestamp="2026-06-18_08-10-00")
    assert m["matched"] is True
    assert m["score"] >= 0.70


def test_predicted_position_improves_score(monkeypatch, tmp_path):
    mod = _lineage(monkeypatch, tmp_path)
    ir = _ir(lon=13.8, vx_deg_min=0.04, vy_deg_min=0.0, bt_trend_k_per_min=-1, cloud_height_trend_m_per_min=50)
    m = mod.compute_ir_radar_match_score(_radar(lon=14.0), ir, timestamp="2026-06-18_08-10-00")
    assert m["predicted_centroid_distance_km"] < m["centroid_distance_km"]
    no_pred = dict(ir); no_pred.pop("vx_deg_min")
    m2 = mod.compute_ir_radar_match_score(_radar(lon=14.0), no_pred, timestamp="2026-06-18_08-10-00")
    assert m["score"] > m2["score"]


def test_select_matches_one_ir_to_best_radar_only(monkeypatch, tmp_path):
    mod = _lineage(monkeypatch, tmp_path)
    radars = [_radar(id="weak", core_ratio=0.2, area=10), _radar(id="strong", core_ratio=0.9, area=30)]
    matches, _ = mod.select_ir_radar_matches(radars, [_ir(bt_trend_k_per_min=-1, cloud_height_trend_m_per_min=50, area_growth_km2_per_min=1)], timestamp="2026-06-18_08-10-00")
    assert len(matches) == 1
    assert radars[matches[0]["radar_index"]]["id"] == "strong"


def test_radar_cell_inherits_ir_cell_id(monkeypatch, tmp_path):
    mod = _lineage(monkeypatch, tmp_path)
    radars, irs, _ = mod.update_cell_lineage([_radar()], [_ir(bt_trend_k_per_min=-1, cloud_height_trend_m_per_min=50, area_growth_km2_per_min=1)], timestamp="2026-06-18_08-10-00")
    assert radars[0]["cell_id"] == irs[0]["cell_id"]


def test_ir_track_hidden_after_radar_confirmation(monkeypatch, tmp_path):
    mod = _lineage(monkeypatch, tmp_path)
    _, irs, _ = mod.update_cell_lineage([_radar()], [_ir(bt_trend_k_per_min=-1, cloud_height_trend_m_per_min=50, area_growth_km2_per_min=1)], timestamp="2026-06-18_08-10-00")
    assert irs[0]["display_as_precursor"] is False
    assert irs[0]["ir_only_precursor"] == 0.0
    assert irs[0]["radar_confirmed"] is True


def test_lineage_state_radar_to_cell_updated(monkeypatch, tmp_path):
    mod = _lineage(monkeypatch, tmp_path)
    mod.update_cell_lineage([_radar(id="42")], [_ir(bt_trend_k_per_min=-1, cloud_height_trend_m_per_min=50, area_growth_km2_per_min=1)], timestamp="2026-06-18_08-10-00")
    state = mod.load_lineage_state()
    assert state["radar_to_cell"]["42"] == "WX-20260618-0001"
    assert state["cells"]["WX-20260618-0001"]["status"] == "radar_confirmed"


def test_ir_to_radar_confirmation_event_written(monkeypatch, tmp_path):
    mod = _lineage(monkeypatch, tmp_path)
    mod.update_cell_lineage([_radar()], [_ir(bt_trend_k_per_min=-1, cloud_height_trend_m_per_min=50, area_growth_km2_per_min=1)], timestamp="2026-06-18_08-10-00")
    rows = [json.loads(x) for x in (tmp_path / "cell_lineage" / "cell_lineage_events.jsonl").read_text().splitlines()]
    assert any(r.get("event_type") == "ir_to_radar_confirmation" for r in rows)


def test_legacy_fallback_still_available():
    text = Path("main.py").read_text(encoding="utf-8")
    assert "def _legacy_ir_radar_distance_match" in text
    assert "Score-Matching fehlgeschlagen, nutze Legacy-IR-Matching" in text
    assert "_legacy_ir_radar_distance_match(objects, _ir_tracks)" in text


def test_no_external_requests_in_score_matching():
    text = Path("cell_lineage.py").read_text(encoding="utf-8")
    assert "import requests" not in text
    assert "import httpx" not in text
    assert "urllib" not in text
