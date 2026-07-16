from datetime import datetime, timedelta, timezone
import hydro_flood_ml as h

def row(station, minute, active=True, lineage="l"):
    return {"station_id":station,"sample_start_time":(datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(minutes=minute)).isoformat(),"precip_event_active":active,"contributing_lineage_ids":[lineage] if active else []}

def test_events_global_chronological_split_and_stable(monkeypatch):
    monkeypatch.setattr(h,"_cfg_int",lambda key,default,*args: 20 if key=="HYDRO_EVENT_DRY_GAP_MIN" else default)
    rows=[row("z",5),row("a",0),row("m",3),row("a",10,False),row("a",30,True)]
    first=h.analyze_training_dataset(rows)
    starts=[h._dt(event[0]["sample_start_time"]) for event in first["events"]]
    assert starts==sorted(starts)
    assert set(r["event_id"] for e in first["train_events"] for r in e).isdisjoint(r["event_id"] for e in first["validation_events"] for r in e)
    assert [r["event_id"] for e in first["events"] for r in e]==[r["event_id"] for e in h.analyze_training_dataset(rows)["events"] for r in e]
