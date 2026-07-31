#!/usr/bin/env python3
"""Read-only, evidence-conservative verification case trace."""
from __future__ import annotations
import argparse, json, os, tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
REPO=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(REPO))
from accuracy_tracker import _haversine_km, _match_valid_b247

def ts(v): return datetime.fromisoformat(v.replace("Z","+00:00"))
def frame_ts(path):
    try: return datetime.strptime(path.stem,"%Y-%m-%d_%H-%M-%S").replace(tzinfo=timezone.utc)
    except ValueError: return None
def atomic(path,data,jsonl=False):
    path.parent.mkdir(parents=True,exist_ok=True); fd,tmp=tempfile.mkstemp(prefix=".trace.",dir=path.parent,text=True)
    with os.fdopen(fd,"w",encoding="utf-8") as f:
        if jsonl:
            for x in data:f.write(json.dumps(x,ensure_ascii=False,sort_keys=True)+"\n")
        else: json.dump(data,f,ensure_ascii=False,indent=2,sort_keys=True); f.write("\n")
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp,path)
def lineage(origin,cand,target):
    oid=str(origin.get("cell_id") or origin.get("id") or ""); cid=str(cand.get("cell_id") or cand.get("id") or "")
    evidence=[]
    if str(cand.get("parent_cell_id") or "")==oid:evidence.append("parent_child")
    if oid in [str(x) for x in cand.get("merged_from_cell_ids") or []]:evidence.append("merge")
    if cid in [str(x) for x in origin.get("alias_cell_ids") or []]:evidence.append("alias")
    if origin.get("radar_track_id") and origin.get("radar_track_id")==cand.get("radar_track_id"):evidence.append("radar_track_continuity")
    stamp=cand.get("lineage_evidence_timestamp") or cand.get("timestamp_utc")
    timely=bool(stamp and ts(str(stamp))<=target)
    return evidence if timely else []
def investigate(a):
    start,end=ts(a.from_utc),ts(a.to_utc); horizons=[int(x) for x in a.horizons.split(",")]
    paths=[]
    for pattern in ("train_data/objects/*.json","train_data/radar/objects/*.json"):
        for p in REPO.glob(pattern):
            t=frame_ts(p)
            if t and start<=t<=end: paths.append((t,p))
    paths=sorted(set(paths)); frames=[]; parsed={}
    for t,p in paths:
        try:data=json.loads(p.read_text(encoding="utf-8")); objs=data if isinstance(data,list) else []
        except Exception:objs=[]
        parsed[t]=(p,objs); frames.append({"frame_id":p.stem,"timestamp_utc":t.isoformat().replace("+00:00","Z"),"path":str(p.relative_to(REPO)),"object_count":len(objs),"object_ids":[str(o.get("id")) for o in objs],"cell_ids":[str(o.get("cell_id")) for o in objs]})
    trace=[]
    for source,(sp,objs) in parsed.items():
        origins=[o for o in objs if str(o.get("id"))==a.object_id or str(o.get("cell_id"))==a.cell_id]
        for origin in origins:
            for h in horizons:
                if origin.get(f"forecast_lat_{h}") is None:continue
                target=source+timedelta(minutes=h); choices=sorted(parsed,key=lambda x:abs((x-target).total_seconds()))
                chosen=choices[0] if choices else None; candidates=parsed[chosen][1] if chosen else []
                for cand in candidates:
                    exact_id=str(cand.get("id"))==a.object_id; exact_cell=str(cand.get("cell_id"))==a.cell_id; ev=lineage(origin,cand,target)
                    try:d=_haversine_km(float(origin[f"forecast_lat_{h}"]),float(origin[f"forecast_lon_{h}"]),float(cand["lat"]),float(cand["lon"]))
                    except Exception:d=None
                    speed_ok=_match_valid_b247(origin,cand,h) if d is not None else False
                    accepted=exact_id or exact_cell or bool(ev)
                    trace.append({"source_frame":sp.stem,"target_timestamp":target.isoformat().replace("+00:00","Z"),"maturity_timestamp":target.isoformat().replace("+00:00","Z"),"selected_target_frame":parsed[chosen][0].stem if chosen else None,"target_delta_min":abs((chosen-target).total_seconds())/60 if chosen else None,"object_inventory":[str(o.get("id")) for o in candidates],"candidate_object_id":cand.get("id"),"candidate_cell_id":cand.get("cell_id"),"exact_id_candidate":exact_id,"cell_id_candidate":exact_cell,"lineage_candidates":ev,"radar_track_id_candidates":bool(origin.get("radar_track_id") and origin.get("radar_track_id")==cand.get("radar_track_id")),"nn_candidates":d is not None,"distance_km":d,"implicit_speed_kmh":None,"speed_gate_result":speed_ok,"core_gate_result":speed_ok,"lineage_evidence":ev,"accept_reject_reason":"gold_identity" if accepted else "unproven_nearest","verification_state":"final" if accepted and chosen==target else ("provisional" if accepted else "invalid"),"gold_actual":accepted})
    status="unresolved"
    evidence={"object_absent":False,"b247_rejected":False,"lineage_confirmed":False,"unproven_nearest":False}
    if trace:
        evidence["object_absent"]=any(a.object_id not in r["object_inventory"] for r in trace)
        evidence["b247_rejected"]=any(r["exact_id_candidate"] and not r["speed_gate_result"] for r in trace)
        evidence["lineage_confirmed"]=any(bool(r["lineage_evidence"]) for r in trace)
        evidence["unproven_nearest"]=any(r["nn_candidates"] and not r["gold_actual"] for r in trace)
    summary={"case":a.cell_id,"object_id":a.object_id,"status":status,"gold_actual":False,"evidence":evidence,"source_frames":len(frames),"candidate_records":len(trace),"caveat":"No root cause is claimed without timestamped evidence."}
    atomic(a.output_dir/"frame_inventory.json",frames); atomic(a.output_dir/"candidate_trace.jsonl",trace,True); atomic(a.output_dir/"summary.json",summary)
    atomic(a.output_dir/"timeline.json",{"case":a.cell_id,"from_utc":a.from_utc,"to_utc":a.to_utc,"events":trace})
    text=f"# Verification timeline {a.cell_id}\n\nStatus: **{status}**\n\nFrames: {len(frames)}; candidates: {len(trace)}.\n\nNo unproven lineage is accepted as a Gold Actual.\n"
    fd,tmp=tempfile.mkstemp(prefix=".trace.",dir=a.output_dir,text=True)
    with os.fdopen(fd,"w",encoding="utf-8") as f:f.write(text);f.flush();os.fsync(f.fileno())
    os.replace(tmp,a.output_dir/"timeline.md")
    return summary
def main():
    p=argparse.ArgumentParser();p.add_argument("--cell-id",required=True);p.add_argument("--object-id",required=True);p.add_argument("--from-utc",required=True);p.add_argument("--to-utc",required=True);p.add_argument("--horizons",required=True);p.add_argument("--output-dir",type=Path,required=True)
    a=p.parse_args();print(json.dumps(investigate(a),ensure_ascii=False))
if __name__=="__main__":main()
