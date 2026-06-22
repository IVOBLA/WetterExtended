import json

import hydro_api


def _patch_paths(monkeypatch, tmp_path):
    generated = tmp_path / "hydro/static/generated"
    live = tmp_path / "hydro/live"
    impact = tmp_path / "hydro/impact"
    generated.mkdir(parents=True)
    live.mkdir(parents=True)
    impact.mkdir(parents=True)
    monkeypatch.setattr(hydro_api, "STATIC_GENERATED", generated)
    monkeypatch.setattr(hydro_api, "LIVE_LATEST", live / "latest_hydro.json")
    monkeypatch.setattr(hydro_api, "LIVE_STATUS", live / "hydro_status.json")
    monkeypatch.setattr(hydro_api, "IMPACT_DIR", impact)
    monkeypatch.setattr(hydro_api, "LATEST_IMPACTS", impact / "latest_hydro_impacts.json")
    monkeypatch.setattr(hydro_api, "VERIFICATIONS", impact / "hydro_verifications.jsonl")
    monkeypatch.setattr(hydro_api, "enabled", lambda: True)
    return generated, live, impact


def test_status_reports_missing_static_files(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)

    status = hydro_api.status()

    assert status["status"] == "hydro_static_missing"
    assert status["static_status"] == "hydro_static_missing"
    assert status["static_ready"] is False


def test_status_reports_invalid_static_status_json(monkeypatch, tmp_path):
    generated, _, _ = _patch_paths(monkeypatch, tmp_path)
    (generated / "hydro_static_status.json").write_text("{kaputt", encoding="utf-8")

    status = hydro_api.status()

    assert status["status"] == "invalid_static_json"
    assert status["static_status"] == "invalid_static_json"
    assert status["static_ready"] is False
    assert "JSON" in status["static_error"] or "Expecting" in status["static_error"]


def test_status_reports_missing_upstream_topology(monkeypatch, tmp_path):
    generated, _, _ = _patch_paths(monkeypatch, tmp_path)
    (generated / "hydro_static_status.json").write_text(json.dumps({"status": "hydro_static_missing"}), encoding="utf-8")
    (generated / "station_network_index.json").write_text(json.dumps({"stations": [{"station_id": "S1", "lon": 13.1, "lat": 46.6, "impact_eligible": False, "source_quality": "upstream_topology_missing", "reason": ["upstream_topology_missing", "station_catchment_unavailable"]}]}), encoding="utf-8")

    status = hydro_api.status()

    assert status["status"] == "upstream_topology_missing"
    assert status["static_status"] == "upstream_topology_missing"
    assert status["static_ready"] is False


def test_status_reports_valid_static_files_as_hydro_ready(monkeypatch, tmp_path):
    generated, live, _ = _patch_paths(monkeypatch, tmp_path)
    (generated / "hydro_static_status.json").write_text(json.dumps({"status": "ok", "ok": True}), encoding="utf-8")
    (generated / "station_network_index.json").write_text(json.dumps({"stations": [{"station_id": "S1", "lon": 13.1, "lat": 46.6, "impact_eligible": True, "enabled": True}]}), encoding="utf-8")
    (live / "latest_hydro.json").write_text(json.dumps({"fetched_at": "2026-06-19T10:00:00Z", "stations": []}), encoding="utf-8")
    (live / "hydro_status.json").write_text(json.dumps({"ok": True, "updated_at": "2026-06-19T10:00:00Z"}), encoding="utf-8")

    status = hydro_api.status()

    assert status["status"] == "hydro_ready"
    assert status["static_status"] == "hydro_static_ready"
    assert status["static_ready"] is True


def test_status_reports_basins_available_and_flowlines_missing(monkeypatch, tmp_path):
    generated, _, _ = _patch_paths(monkeypatch, tmp_path)
    (generated / "hydro_static_status.json").write_text(json.dumps({"status": "upstream_topology_missing", "basin_count": 2, "flowline_count": 0}), encoding="utf-8")
    (generated / "station_network_index.json").write_text(json.dumps({"stations": [{"station_id": "S1", "lon": 14.1, "lat": 46.7, "impact_eligible": False, "source_quality": "upstream_topology_missing", "reason": ["upstream_topology_missing"]}]}), encoding="utf-8")

    status = hydro_api.status()

    assert status["basins_available"] is True
    assert status["flowlines_available"] is False
    assert status["hydro_static_missing"] is False
    assert status["impact_not_eligible_reason"] == "flowlines_missing"


def test_status_reports_feldkirchen_coverage_ok(monkeypatch, tmp_path):
    generated, live, _ = _patch_paths(monkeypatch, tmp_path)
    (generated / "hydro_static_status.json").write_text(json.dumps({"status": "ok", "ok": True, "basin_count": 1, "flowline_count": 1, "feldkirchen_coverage": {"coverage_ok": True}}), encoding="utf-8")
    (generated / "station_network_index.json").write_text(json.dumps({"stations": [{"station_id": "S1", "lon": 14.1, "lat": 46.7, "impact_eligible": True, "enabled": True}]}), encoding="utf-8")
    (live / "latest_hydro.json").write_text(json.dumps({"stations": []}), encoding="utf-8")

    status = hydro_api.status()

    assert status["static_status"] == "hydro_static_ready"
    assert status["basins_available"] is True
    assert status["flowlines_available"] is True
    assert status["feldkirchen_coverage_ok"] is True


def test_status_prefers_flowlines_missing_for_basin_only(monkeypatch, tmp_path):
    generated, _, _ = _patch_paths(monkeypatch, tmp_path)
    (generated / "hydro_static_status.json").write_text(json.dumps({"status": "upstream_topology_missing", "basin_count": 2, "flowline_count": 0}), encoding="utf-8")
    (generated / "station_network_index.json").write_text(json.dumps({"stations": [{"station_id": "S1", "impact_eligible": False, "source_quality": "upstream_topology_missing", "reason": ["upstream_topology_missing"]}]}), encoding="utf-8")

    status = hydro_api.status()

    assert status["static_status"] == "flowlines_missing"
    assert status["impact_not_eligible_reason"] == "flowlines_missing"
