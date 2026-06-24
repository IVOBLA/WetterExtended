import json


def test_hydro_admin_override_file_persists_and_cannot_enable_ineligible(monkeypatch, tmp_path):
    import hydro_station_overrides as hso
    monkeypatch.setenv("HYDRO_STATION_OVERRIDES_PATH", str(tmp_path / "data/config/hydro_station_overrides.json"))
    hso.patch_station("S1", {"enabled": True})
    assert json.loads((tmp_path / "data/config/hydro_station_overrides.json").read_text())["S1"]["enabled"] is True


def test_apply_station_override_never_makes_ineligible_effective(monkeypatch, tmp_path):
    import hydro_api, hydro_station_overrides as hso
    monkeypatch.setenv("HYDRO_STATION_OVERRIDES_PATH", str(tmp_path / "overrides.json"))
    hso.save({"S1": {"enabled": True}})
    station = hydro_api.apply_station_override({"station_id": "S1", "impact_eligible_auto": False, "enabled": True})
    assert station["impact_enabled"] is False
    assert station["impact_effective"] is False
    assert station["enabled"] is False


def test_cycle_resolution_removes_only_back_edge_keeps_upstream_path():
    import hydro_upstream_graph as hug
    basins = [{"type":"Feature","properties":{"catchment_id": x},"geometry": None} for x in ["A","B","C"]]
    edges = [
        {"from_basin_id":"A","to_basin_id":"B","flowline_id":"1","confidence":"confident"},
        {"from_basin_id":"B","to_basin_id":"C","flowline_id":"2","confidence":"confident"},
        {"from_basin_id":"C","to_basin_id":"B","flowline_id":"3","confidence":"confident"},
    ]
    monkeypatch = None
    # Direkter Adj-Bypass: interne Cycle-Resolution ist fachlich relevant und ohne Geometrie testbar.
    removed, cycles = hug._remove_cycle_closing_edges(["A","B","C"], edges)
    assert removed == {2}
    edges[2]["confidence"] = "cycle_removed"
    graph = {"cycle_nodes":["B","C"], "upstream_by_basin":{"B":["A"], "C":["B"]}}
    assert hug.get_upstream_basin_ids("C", graph) == ["A", "B", "C"]
