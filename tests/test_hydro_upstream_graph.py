import json
from pathlib import Path

import pytest

import hydro_upstream_graph as hug
from hydro_station_index import build_station_index, SHAPELY_AVAILABLE


def basin(bid, x0, x1):
    return {"type":"Feature","properties":{"HYDROID":bid},"geometry":{"type":"Polygon","coordinates":[[[x0,0],[x1,0],[x1,1],[x0,1],[x0,0]]]}}

def basin_with_downstream(bid, x0, x1, downstream=None):
    b = basin(bid, x0, x1)
    if downstream:
        b["properties"]["downstream_basin_id"] = downstream
    return b

def flow(fid, coords, direction="forward"):
    return {"type":"Feature","properties":{"HYDROID":fid,"STARTNODE_HREF":f"{fid}s","ENDNODE_HREF":f"{fid}e","FLOWDIRECTION":direction,"INNETWORK":True},"geometry":{"type":"LineString","coordinates":coords}}


def test_build_flowline_graph_uses_start_end_nodes():
    g=hug.build_flowline_graph([flow("F1", [[0.2,0.5],[1.8,0.5]])])
    assert g["edges"][0]["from_node"] == "F1s"
    assert g["edges"][0]["to_node"] == "F1e"


def test_flowdirection_reverse_is_handled():
    g=hug.build_flowline_graph([flow("F1", [[0.2,0.5],[1.8,0.5]], "reverse")])
    assert g["edges"][0]["from_node"] == "F1e"
    assert g["edges"][0]["to_node"] == "F1s"


def test_unknown_flowdirection_is_diagnostic_only():
    g=hug.build_flowline_graph([flow("F1", [[0.2,0.5],[1.8,0.5]], "unknown")])
    assert g["edges"] == []
    assert g["diagnostic_flowlines"][0]["reason"] == "flowline_direction_missing"

@pytest.mark.skipif(not hug.SHAPELY_AVAILABLE, reason="Shapely fehlt")
def test_flowline_to_basin_mapping_by_geometry():
    matches=hug.map_flowlines_to_basins([flow("F1", [[0.2,0.5],[1.8,0.5]])], [basin("B1",0,1), basin("B2",1,2)])
    assert matches["F1"]["basin_ids"] == ["B1", "B2"]
    assert matches["F1"]["flowline_basin_match_method" if False else "method"] == "geometry"

@pytest.mark.skipif(not hug.SHAPELY_AVAILABLE, reason="Shapely fehlt")
def test_basin_adjacency_from_directed_flowlines():
    adj=hug.build_basin_adjacency_from_flowlines([flow("F1", [[0.2,0.5],[1.8,0.5]])], [basin("B1",0,1), basin("B2",1,2)])
    assert adj["edges"][0]["from_basin_id"] == "B1"
    assert adj["edges"][0]["to_basin_id"] == "B2"

@pytest.mark.skipif(not hug.SHAPELY_AVAILABLE, reason="Shapely fehlt")
def test_upstream_ids_from_basin_graph():
    g=hug.build_upstream_basin_graph([basin("B1",0,1), basin("B2",1,2), basin("B3",2,3)], [flow("F1", [[0.2,.5],[1.8,.5]]), flow("F2", [[1.2,.5],[2.8,.5]])])
    assert hug.get_upstream_basin_ids("B3", g) == ["B1", "B2", "B3"]

@pytest.mark.skipif(not hug.SHAPELY_AVAILABLE, reason="Shapely fehlt")
def test_cycle_detection_removes_only_back_edge_and_keeps_upstream():
    bs=[basin("B1",0,1), basin("B2",1,2)]
    g=hug.build_upstream_basin_graph(bs, [flow("F1", [[0.2,.5],[1.8,.5]]), flow("F2", [[1.8,.6],[0.2,.6]])])
    assert g["cycle_count"] > 0
    assert g["cycle_removed_edge_count"] == 1
    assert hug.get_upstream_basin_ids("B2", g) == ["B1", "B2"]

@pytest.mark.skipif(not SHAPELY_AVAILABLE, reason="Shapely fehlt")
def test_station_gets_upstream_union_when_graph_confident(tmp_path):
    stations={"type":"FeatureCollection","features":[{"type":"Feature","properties":{"station_id":"S"},"geometry":{"type":"Point","coordinates":[1.5,.5]}}]}
    sp=tmp_path/"s.geojson"; bp=tmp_path/"b.geojson"; fp=tmp_path/"f.geojson"
    sp.write_text(json.dumps(stations)); bp.write_text(json.dumps({"type":"FeatureCollection","features":[basin("B1",0,1),basin("B2",1,2)]})); fp.write_text(json.dumps({"type":"FeatureCollection","features":[flow("F1", [[0.2,.5],[1.8,.5]])]}))
    st=build_station_index(str(sp), str(bp), str(fp), str(tmp_path))
    assert st["status"] in {"hydro_static_ready", "upstream_topology_partial", "ok"}
    row=json.loads((tmp_path/"station_network_index.json").read_text())["by_station_id"]["S"]
    assert row["impact_eligible"] is True
    assert set(row["upstream_catchment_ids"]) == {"B1","B2"}

@pytest.mark.skipif(not SHAPELY_AVAILABLE, reason="Shapely fehlt")
def test_station_without_confident_graph_stays_not_eligible(tmp_path):
    stations={"type":"FeatureCollection","features":[{"type":"Feature","properties":{"station_id":"S"},"geometry":{"type":"Point","coordinates":[1.5,.5]}}]}
    sp=tmp_path/"s.geojson"; bp=tmp_path/"b.geojson"; fp=tmp_path/"f.geojson"
    sp.write_text(json.dumps(stations)); bp.write_text(json.dumps({"type":"FeatureCollection","features":[basin("B1",0,1),basin("B2",1,2)]})); fp.write_text(json.dumps({"type":"FeatureCollection","features":[flow("F1", [[0.2,.5],[1.8,.5]], "unknown")]}))
    build_station_index(str(sp), str(bp), str(fp), str(tmp_path))
    row=json.loads((tmp_path/"station_network_index.json").read_text())["by_station_id"]["S"]
    assert row["impact_eligible"] is False
    assert "upstream_catchment_unavailable" in row["reason"]


@pytest.mark.skipif(not SHAPELY_AVAILABLE, reason="Shapely fehlt")
def test_station_uses_basin_topology_fallback_when_flowline_graph_unusable(tmp_path):
    stations={"type":"FeatureCollection","features":[{"type":"Feature","properties":{"station_id":"S"},"geometry":{"type":"Point","coordinates":[1.5,.5]}}]}
    sp=tmp_path/"s.geojson"; bp=tmp_path/"b.geojson"; fp=tmp_path/"f.geojson"
    sp.write_text(json.dumps(stations))
    bp.write_text(json.dumps({"type":"FeatureCollection","features":[basin_with_downstream("B1",0,1,"B2"),basin("B2",1,2)]}))
    fp.write_text(json.dumps({"type":"FeatureCollection","features":[flow("F1", [[0.2,.5],[1.8,.5]], "unknown")]}))
    build_station_index(str(sp), str(bp), str(fp), str(tmp_path))
    row=json.loads((tmp_path/"station_network_index.json").read_text())["by_station_id"]["S"]
    assert row["impact_eligible_auto"] is True
    assert row["topology_source"] == "ggn_basin_downstream_topology"
    assert set(row["upstream_catchment_ids"]) == {"B1","B2"}


def test_no_external_requests_in_upstream_graph_build(monkeypatch):
    try:
        import requests  # noqa: F401
    except Exception:
        requests = None
    if requests is not None:
        def boom(*a, **k): raise AssertionError("external request")
        monkeypatch.setattr("requests.get", boom)
    hug.build_flowline_graph([flow("F1", [[0,0],[1,1]])])
