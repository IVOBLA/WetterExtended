import glob
import json
import math
import os
from datetime import datetime, timedelta
from typing import Optional
from config import SAVE_PATHS
EVAL_DIR = SAVE_PATHS.get("evaluation", "train_data/evaluation/")
def _parse_ts(name: str) -> Optional[datetime]:
    base = os.path.splitext(os.path.basename(name))[0]
    try:return datetime.strptime(base, "%Y-%m-%d_%H-%M-%S")
    except ValueError:return None
def _load_objects(path: str) -> list:
    try:
        with open(path, "r", encoding="utf-8") as f:return json.load(f)
    except Exception:return []
def evaluate_for_horizon(horizon_min: int, since_hours: int = 24) -> dict:
    obj_dir = SAVE_PATHS["objects"]; files = sorted(glob.glob(os.path.join(obj_dir, "*.json"))); files_with_ts=[(f,_parse_ts(f)) for f in files]; files_with_ts=[(f,ts) for f,ts in files_with_ts if ts is not None]
    if not files_with_ts:return {"horizon":horizon_min,"samples":0,"mae_px":None,"since_hours":since_hours}
    cutoff = files_with_ts[-1][1] - timedelta(hours=since_hours); by_ts={ts:f for f,ts in files_with_ts}; n=0;sse_x=0.0;sse_y=0.0;abs_sum=0.0
    for fpath,ts in files_with_ts:
      if ts<cutoff: continue
      objs=_load_objects(fpath); target_ts=ts+timedelta(minutes=horizon_min); target_path=None
      for cand_ts,cand_f in by_ts.items():
        if abs((cand_ts-target_ts).total_seconds())<=90: target_path=cand_f; break
      if target_path is None: continue
      target_by_id={str(o.get("id")):o for o in _load_objects(target_path) if isinstance(o,dict) and "id" in o}
      for obj in objs:
        oid=str(obj.get("id")); fx=obj.get(f"forecast_x_{horizon_min}"); fy=obj.get(f"forecast_y_{horizon_min}")
        if fx is None or fy is None or oid not in target_by_id: continue
        real=target_by_id[oid]
        try:
          rx=float(real.get("x",0.0)); ry=float(real.get("y",0.0)); ex=float(fx)-rx; ey=float(fy)-ry; sse_x+=ex*ex; sse_y+=ey*ey; abs_sum+=math.hypot(ex,ey); n+=1
        except Exception: continue
    return {"horizon":horizon_min,"samples":n,"mae_px":(abs_sum/n) if n else None,"rmse_x_px":math.sqrt(sse_x/n) if n else None,"rmse_y_px":math.sqrt(sse_y/n) if n else None,"since_hours":since_hours}
def evaluate_all(horizons: list, since_hours: int = 24) -> dict:return {"since_hours":since_hours,"horizons":[evaluate_for_horizon(h,since_hours) for h in horizons]}
def append_history_point(metric: dict) -> str:
    os.makedirs(EVAL_DIR, exist_ok=True); path=os.path.join(EVAL_DIR,"accuracy_history.jsonl"); metric["timestamp_utc"]=datetime.utcnow().isoformat()+"Z"
    with open(path,"a",encoding="utf-8") as f:f.write(json.dumps(metric,ensure_ascii=False)+"\n")
    return path
def load_history(since_hours: int = 24*7) -> list:
    path=os.path.join(EVAL_DIR,"accuracy_history.jsonl")
    if not os.path.exists(path): return []
    cutoff=datetime.utcnow()-timedelta(hours=since_hours); out=[]
    with open(path,"r",encoding="utf-8") as f:
      for line in f:
        try:
          rec=json.loads(line.strip()); ts=datetime.fromisoformat(rec.get("timestamp_utc","").replace("Z",""))
          if ts>=cutoff: out.append(rec)
        except Exception: pass
    return out
