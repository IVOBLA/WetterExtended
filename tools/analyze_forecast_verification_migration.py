#!/usr/bin/env python3
"""Read-only assessment of legacy verification JSONL before explicit migration."""
from __future__ import annotations
import argparse, hashlib, json, os, tempfile
from pathlib import Path
import sys
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from forecast_verification import CASE_FIELDS, build_case_key

REQUIRED = set(CASE_FIELDS) - {"origin_radar_track_id"}

def atomic_jsonl(path: Path, rows):
    fd, tmp = tempfile.mkstemp(prefix=".migration.", dir=path.parent, text=True)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for row in rows: f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)

def atomic_text(path: Path, text: str):
    fd,tmp=tempfile.mkstemp(prefix=".migration.",dir=path.parent,text=True)
    with os.fdopen(fd,"w",encoding="utf-8") as f: f.write(text); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,path)

def normalize(row):
    r = dict(row)
    r.setdefault("origin_object_id", r.get("object_id")); r.setdefault("origin_cell_id", r.get("cell_id"))
    r.setdefault("origin_radar_track_id", r.get("track_id") or None)
    r.setdefault("forecast_source_frame_id", r.get("source_frame_id") or r.get("forecast_created_at_utc"))
    return r

def analyze(details: Path, output: Path):
    before = hashlib.sha256(details.read_bytes()).hexdigest() if details.exists() else None
    valid=[]; legacy=[]
    if details.exists():
        for no,line in enumerate(details.read_text(encoding="utf-8", errors="replace").splitlines(),1):
            try: r=normalize(json.loads(line))
            except Exception: legacy.append({"line":no,"reason":"invalid_json"}); continue
            missing=sorted(k for k in REQUIRED if r.get(k) in (None,""))
            if missing: legacy.append({"line":no,"reason":"missing_schema_fields","missing_fields":missing,"record":r}); continue
            r["case_key"]=build_case_key(r); r["legacy_line"]=no; valid.append(r)
    groups={}
    for r in valid: groups.setdefault(r["case_key"],[]).append(r)
    duplicates=[]; conflicts=[]; latest=[]
    for key, rows in groups.items():
        if len(rows)>1: duplicates.append({"case_key":key,"count":len(rows),"lines":[r["legacy_line"] for r in rows]})
        actuals={(r.get("actual_lat"),r.get("actual_lon"),r.get("matched_object_id")) for r in rows}
        types={str(r.get("match_type")) for r in rows}; pending=any(r.get("verification_state")=="pending" or r.get("missing_target_frame_reason")=="missing_due_to_future_not_available" for r in rows)
        ambiguous=any(t in {"nearest","nn"} for t in types)
        if len(actuals)>1 or len(types)>1 or (pending and len(rows)>1) or ambiguous:
            conflicts.append({"case_key":key,"actuals":[list(x) for x in actuals],"match_types":sorted(types),"pending_plus_result":pending and len(rows)>1,"ambiguous_nearest":ambiguous,"lines":[r["legacy_line"] for r in rows]})
        exact=[r for r in rows if r.get("match_type") in ("id","cell_id") and r.get("target_frame_delta_min") in (0,0.0)]
        latest.append((exact or rows)[-1])
    output.mkdir(parents=True,exist_ok=True)
    atomic_jsonl(output/"duplicates.jsonl",duplicates); atomic_jsonl(output/"conflicting_actuals.jsonl",conflicts)
    atomic_jsonl(output/"legacy_incomparable.jsonl",legacy); atomic_jsonl(output/"proposed_latest_view.jsonl",latest)
    summary={"source":str(details),"source_sha256":before,"records":len(valid)+len(legacy),"comparable":len(valid),"legacy_incomparable":len(legacy),"duplicate_cases":len(duplicates),"conflicting_cases":len(conflicts),"proposed_latest":len(latest),"read_only":True}
    atomic_text(output/"summary.json",json.dumps(summary,indent=2,ensure_ascii=False)+"\n")
    atomic_text(output/"report.md","# Forecast verification migration analysis\n\n"+"\n".join(f"- **{k}**: {v}" for k,v in summary.items())+"\n\nNo migration was performed. Review this report before an explicit migration.\n")
    after=hashlib.sha256(details.read_bytes()).hexdigest() if details.exists() else None
    if before != after: raise RuntimeError("legacy input changed during read-only analysis")
    return summary

def main():
    p=argparse.ArgumentParser(); p.add_argument("--details",type=Path,required=True); p.add_argument("--output",type=Path,required=True)
    a=p.parse_args(); print(json.dumps(analyze(a.details,a.output),ensure_ascii=False))
if __name__=="__main__": main()
