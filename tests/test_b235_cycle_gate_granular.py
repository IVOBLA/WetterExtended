"""B235 — Per-Station-Cycle-Gate statt globaler Netzsperre.

Belegt, dass eine zyklenfreie Teilkomponente Upstream-Eignung erhält,
obwohl an anderer Stelle im Netz ein Zyklus existiert, während Zyklus-Knoten
weiterhin konservativ ausgeschlossen bleiben (keine Über-Attribution).
"""

import hydro_upstream_graph as hug
import pytest


def _basin(bid, x0, x1):
    return {"type": "Feature", "properties": {"HYDROID": bid},
            "geometry": {"type": "Polygon", "coordinates": [[[x0, 0], [x1, 0], [x1, 1], [x0, 1], [x0, 0]]]}}


def _flow(fid, coords, direction="forward"):
    return {"type": "Feature",
            "properties": {"HYDROID": fid, "STARTNODE_HREF": fid + "s", "ENDNODE_HREF": fid + "e",
                           "FLOWDIRECTION": direction, "INNETWORK": True},
            "geometry": {"type": "LineString", "coordinates": coords}}


def test_get_upstream_uses_cycle_nodes_not_global_count():
    # Reiner Dict-Test (ohne Shapely): zyklenfreie Station bekommt Upstream,
    # Zyklus-Knoten wird ausgeschlossen, obwohl cycle_count > 0.
    graph = {"cycle_count": 1, "cycle_nodes": ["X1", "X2"],
             "upstream_by_basin": {"S": ["U1"], "U1": ["U2"], "X2": ["X1"]}}
    assert hug.get_upstream_basin_ids("S", graph) == ["S", "U1", "U2"]
    assert hug.get_upstream_basin_ids("X2", graph) == ["X1", "X2"]


def test_empty_station_id_returns_empty():
    assert hug.get_upstream_basin_ids("", {"cycle_nodes": [], "upstream_by_basin": {}}) == []


@pytest.mark.skipif(not hug.SHAPELY_AVAILABLE, reason="Shapely fehlt")
def test_cycle_free_component_eligible_despite_global_cycle():
    basins = [_basin("B1", 0, 1), _basin("B2", 1, 2),
              _basin("B3", 3, 4), _basin("B4", 4, 5), _basin("B5", 5, 6)]
    flows = [_flow("F1", [[0.2, .5], [1.8, .5]]), _flow("F2", [[1.8, .6], [0.2, .6]]),  # Zyklus B1<->B2
             _flow("F3", [[3.2, .5], [4.8, .5]]), _flow("F4", [[4.2, .5], [5.8, .5]])]  # Kette B3->B4->B5
    g = hug.build_upstream_basin_graph(basins, flows)
    assert g["cycle_count"] > 0
    assert "cycle_nodes" in g and set(g["cycle_nodes"]) == {"B1", "B2"}
    # NEU: zyklenfreie Kette liefert vollen Upstream trotz globalem Zyklus
    assert hug.get_upstream_basin_ids("B5", g) == ["B3", "B4", "B5"]
    # NEU: Auch Zyklus-Knoten werden nicht global gesperrt; nur die Rueckkante fehlt.
    assert hug.get_upstream_basin_ids("B2", g) == ["B1", "B2"]


@pytest.mark.skipif(not hug.SHAPELY_AVAILABLE, reason="Shapely fehlt")
def test_fully_cycle_free_graph_unchanged():
    basins = [_basin("B1", 0, 1), _basin("B2", 1, 2), _basin("B3", 2, 3)]
    flows = [_flow("F1", [[0.2, .5], [1.8, .5]]), _flow("F2", [[1.2, .5], [2.8, .5]])]
    g = hug.build_upstream_basin_graph(basins, flows)
    assert g["cycle_count"] == 0
    assert g["cycle_nodes"] == []
    assert hug.get_upstream_basin_ids("B3", g) == ["B1", "B2", "B3"]
