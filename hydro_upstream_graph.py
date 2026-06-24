"""Hydro-Upstream-Graph aus GGN DRAINAGEBASIN und WATERCOURSELINK.

Konservativ: Nur eindeutig gerichtete Flowlines und eindeutig geordnete Basin-
Schnitte werden als belastbare Kanten fuer Hydro-Impact freigegeben.
"""
from __future__ import annotations

import json, os
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hydro_geography import polygon_area_km2

try:
    from shapely.geometry import shape, mapping, LineString, MultiLineString
    from shapely.ops import unary_union
    from shapely.validation import make_valid
    SHAPELY_AVAILABLE = True
except Exception:
    shape = mapping = unary_union = make_valid = LineString = MultiLineString = None
    SHAPELY_AVAILABLE = False

ID_FIELDS = ["catchment_id","basin_id","HYDROID","ID","IDENTIFIER","INSPIREID_IDENTIFIER_LOCALID","id","OBJECTID"]
FLOW_ID_FIELDS = ["flowline_id","HYDROID","ID","IDENTIFIER","INSPIREID_IDENTIFIER_LOCALID","id","OBJECTID"]


def _props(f: dict) -> dict: return f.get("properties") or {}
def _prop(f: dict, names: list[str], default=None):
    p=_props(f)
    low={str(k).lower():v for k,v in p.items()}
    for n in names:
        if n in p and p[n] not in (None,""): return p[n]
        v=low.get(n.lower())
        if v not in (None,""): return v
    return default

def _read_features(path) -> list[dict]:
    with open(path, encoding="utf-8") as fh: data=json.load(fh)
    return data.get("features", []) if isinstance(data, dict) else []

def load_basin_features(path) -> list[dict]: return _read_features(path)
def load_flowline_features(path) -> list[dict]: return _read_features(path)

def normalize_basin_id(feature) -> str:
    val=_prop(feature, ID_FIELDS)
    return str(val) if val not in (None,"") else ""

def normalize_flowline_id(feature) -> str:
    val=_prop(feature, FLOW_ID_FIELDS)
    return str(val) if val not in (None,"") else ""

def _truthy(v) -> bool:
    return str(v).strip().lower() in {"1","true","yes","y","ja","wahr"}

def _in_network(v) -> bool:
    if v in (None,""): return True
    return str(v).strip().lower() not in {"0","false","no","n","nein"}

def extract_flowline_nodes(feature) -> dict:
    p=_props(feature)
    start=_prop(feature,["STARTNODE_HREF","STARTNODE","START_NODE","from_node","fromnode"])
    end=_prop(feature,["ENDNODE_HREF","ENDNODE","END_NODE","to_node","tonode"])
    raw=str(_prop(feature,["FLOWDIRECTION","flow_direction","direction"],"")).strip().lower()
    direction="unknown"
    reverse_tokens={"-1","reverse","reversed","against","opposite","negative","end_to_start","end-start"}
    forward_tokens={"1","true","withdigitised","with_digitized","withdigitized","forward","start_to_end","start-end","positive","in_direction"}
    if raw in forward_tokens or "with" in raw: direction="forward"
    elif raw in reverse_tokens or "against" in raw or "opposite" in raw: direction="reverse"
    elif raw in {"unknown","","0","both","indeterminate","unbekannt"}: direction="unknown"
    if start and end and direction == "forward": up,down=str(start),str(end)
    elif start and end and direction == "reverse": up,down=str(end),str(start)
    else: up=down=None
    return {"start_node": str(start) if start else None, "end_node": str(end) if end else None, "flowdirection": raw, "direction": direction, "upstream_node": up, "downstream_node": down, "directed": bool(up and down), "fictitious": _truthy(_prop(feature,["FICTITIOUS","fictitious"])), "in_network": _in_network(_prop(feature,["INNETWORK","in_network"]))}

def build_flowline_graph(flowlines) -> dict:
    nodes=set(); edges=[]; diagnostic=[]
    for fl in flowlines:
        fid=normalize_flowline_id(fl); n=extract_flowline_nodes(fl)
        if n["start_node"]: nodes.add(n["start_node"])
        if n["end_node"]: nodes.add(n["end_node"])
        if n["directed"] and n["in_network"]:
            edges.append({"from_node":n["upstream_node"],"to_node":n["downstream_node"],"flowline_id":fid,"confidence":"confident","fictitious":n["fictitious"]})
        else:
            diagnostic.append({"flowline_id":fid,"reason":"flowline_direction_missing" if not n["directed"] else "flowline_not_in_network", **n})
    return {"nodes": sorted(nodes), "edges": edges, "diagnostic_flowlines": diagnostic}

def _line_geom(feature):
    if not SHAPELY_AVAILABLE: return None
    try: return shape(feature.get("geometry") or {})
    except Exception: return None

def _basin_geom(feature):
    if not SHAPELY_AVAILABLE: return None
    try:
        g=shape(feature.get("geometry") or {})
        return make_valid(g) if not g.is_valid else g
    except Exception: return None

def map_flowlines_to_basins(flowlines, basins) -> dict:
    basin_geoms=[(normalize_basin_id(b), _basin_geom(b)) for b in basins if normalize_basin_id(b)]
    out={}
    for fl in flowlines:
        fid=normalize_flowline_id(fl); direct=_prop(fl,["catchment_id","basin_id","DRAINAGEBASIN","drainage_basin_id"])
        if direct:
            vals=[str(direct)] if not isinstance(direct,list) else [str(v) for v in direct]
            out[fid]={"flowline_id":fid,"basin_ids":vals,"quality":"confident","method":"attribute","candidates":vals,"flowline_basin_match_quality":"confident","flowline_basin_match_method":"attribute","flowline_basin_candidates":vals}; continue
        line=_line_geom(fl); candidates=[]
        if line is not None:
            for bid,bg in basin_geoms:
                if bg is not None and line.intersects(bg):
                    inter=line.intersection(bg)
                    if not inter.is_empty:
                        candidates.append((float(line.project(inter.representative_point())), bid))
        candidates=sorted(candidates)
        ids=[bid for _,bid in candidates]
        unique=[]
        for bid in ids:
            if bid not in unique: unique.append(bid)
        quality="confident" if unique else "missing"
        out[fid]={"flowline_id":fid,"basin_ids":unique,"quality":quality,"method":"geometry" if unique else "none","candidates":unique,"flowline_basin_match_quality":quality,"flowline_basin_match_method":"geometry" if unique else "none","flowline_basin_candidates":unique}
    return out

def build_basin_adjacency_from_flowlines(flowlines, basins) -> dict:
    matches=map_flowlines_to_basins(flowlines, basins); edges=[]; diag=[]; seen=set()
    for fl in flowlines:
        fid=normalize_flowline_id(fl); nodes=extract_flowline_nodes(fl); m=matches.get(fid,{})
        ids=m.get("basin_ids") or []
        if not nodes["directed"] or not nodes["in_network"]:
            diag.append({"flowline_id":fid,"reason":"flowline_direction_missing"}); continue
        if len(ids) < 2: continue
        ordered=list(ids)
        if nodes["direction"] == "reverse": ordered=list(reversed(ordered))
        for a,b in zip(ordered, ordered[1:]):
            if a==b: continue
            key=(a,b,fid)
            if key in seen: continue
            seen.add(key); edges.append({"from_basin_id":a,"to_basin_id":b,"flowline_id":fid,"confidence":"confident","method":m.get("method","geometry"),"fictitious":nodes["fictitious"]})
    return {"edges":edges,"matches":matches,"diagnostics":diag}

def _cycles(nodes, edges):
    adj=defaultdict(list)
    for e in edges: adj[e["from_basin_id"]].append(e["to_basin_id"])
    visiting=set(); visited=set(); found=[]
    def dfs(n,path):
        visiting.add(n); path.append(n)
        for nb in adj[n]:
            if nb in visiting: found.append(path[path.index(nb):]+[nb])
            elif nb not in visited: dfs(nb,path)
        path.pop(); visiting.remove(n); visited.add(n)
    for n in nodes:
        if n not in visited: dfs(n,[])
    return found

def _remove_cycle_closing_edges(nodes, edges):
    """Markiert nur DFS-Rueckkanten als cycle_removed und behaelt alle anderen Kanten.

    Cycle-Nodes werden weiter traversiert; Endlosschleifen verhindert die DFS-
    Farbe/visited-Logik. Damit werden lokale Zyklen nicht mehr als globale
    Basin-/Stationssperre behandelt.
    """
    by_from=defaultdict(list)
    for idx,e in enumerate(edges):
        by_from[e["from_basin_id"]].append((idx,e))
    visiting=set(); visited=set(); removed=set(); cycles=[]
    def dfs(n,path):
        visiting.add(n); path.append(n)
        for idx,e in by_from.get(n,[]):
            nb=e["to_basin_id"]
            if nb in visiting:
                removed.add(idx); cycles.append(path[path.index(nb):]+[nb])
            elif nb not in visited:
                dfs(nb,path)
        path.pop(); visiting.remove(n); visited.add(n)
    for n in nodes:
        if n not in visited: dfs(n,[])
    return removed, cycles

def build_upstream_basin_graph(basins, flowlines) -> dict:
    ids=[normalize_basin_id(b) for b in basins if normalize_basin_id(b)]
    adj=build_basin_adjacency_from_flowlines(flowlines, basins); edges=adj["edges"]
    removed_edges, cycles = _remove_cycle_closing_edges(ids, edges); cyc_nodes={x for c in cycles for x in c}
    up=defaultdict(list); down=defaultdict(list)
    for idx,e in enumerate(edges):
        if idx in removed_edges:
            e["confidence"]="cycle_removed"; e["cycle_resolution"]="removed_back_edge"; continue
        down[e["from_basin_id"]].append(e["to_basin_id"]); up[e["to_basin_id"]].append(e["from_basin_id"])
    confident=sum(1 for e in edges if e.get("confidence")=="confident")
    return {"nodes":ids,"edges":edges,"upstream_by_basin":{k:sorted(set(v)) for k,v in up.items()},"downstream_by_basin":{k:sorted(set(v)) for k,v in down.items()},"confident_edge_count":confident,"cycle_count":len(cycles),"cycle_removed_edge_count":len(removed_edges),"cycle_nodes":sorted(cyc_nodes),"cycles":cycles,"matches":adj["matches"],"diagnostics":adj["diagnostics"],"topology_quality":"confident" if confident else ("upstream_topology_missing" if not edges else "cycle_edges_removed")}

def get_upstream_basin_ids(station_basin_id, graph) -> list[str]:
    if not station_basin_id: return []
    if str(station_basin_id) in {str(x) for x in (graph.get("cycle_nodes") or [])}:
        return []
    seen={str(station_basin_id)}; q=deque([str(station_basin_id)])
    up=graph.get("upstream_by_basin") or {}
    while q:
        cur=q.popleft()
        for nb in up.get(cur,[]):
            if nb not in seen: seen.add(nb); q.append(nb)
    return sorted(seen) if len(seen)>1 else []

def build_upstream_union_geometry(upstream_basin_ids, basin_by_id) -> dict | None:
    if not upstream_basin_ids or not SHAPELY_AVAILABLE: return None
    geoms=[]
    for bid in upstream_basin_ids:
        g=_basin_geom(basin_by_id.get(bid) or {})
        if g is not None and not g.is_empty: geoms.append(g)
    if not geoms: return None
    u=unary_union(geoms)
    return mapping(make_valid(u) if not u.is_valid else u)

def write_upstream_diagnostics(graph, output_dir, basins=None) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    graph_path=Path(output_dir)/"hydro_upstream_graph.json"
    graph_path.write_text(json.dumps(graph, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    fc={"type":"FeatureCollection","features":[{"type":"Feature","geometry":None,"properties":e} for e in graph.get("edges",[])]}
    (Path(output_dir)/"hydro_upstream_edges.geojson").write_text(json.dumps(fc, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    mfc={"type":"FeatureCollection","features":[{"type":"Feature","geometry":None,"properties":m} for m in (graph.get("matches") or {}).values()]}
    (Path(output_dir)/"hydro_flowline_basin_matches.geojson").write_text(json.dumps(mfc, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    return {"ok": True, "graph_node_count": len(graph.get("nodes",[])), "graph_edge_count": len(graph.get("edges",[])), "confident_edge_count": graph.get("confident_edge_count",0), "cycle_count": graph.get("cycle_count",0), "generated_at": datetime.now(timezone.utc).isoformat()}
