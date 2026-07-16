from datetime import datetime, timedelta, timezone
import hydro_flood_ml as h


def _row(i, minutes, cell='c1'):
    features={k:1.0 for k in h.HYDRO_FLOOD_ML_FEATURES}
    ts=(datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(minutes=minutes)).isoformat().replace('+00:00','Z')
    return {'sample_id':str(i),'station_id':'s','sample_kind':h.SAMPLE_KIND_LIVE,'feature_schema_version':h.FEATURE_SCHEMA_VERSION,'feature_snapshot_complete':True,'target_missing':False,'target_q_delta_m3s':1.0,'sample_start_time':ts,'features':features,'contributing_cell_ids':[cell],'contributing_lineage_ids':[cell],'precip_event_active':True}


def test_single_event_has_no_validation_overlap_and_is_insufficient():
    rows=[_row(i,i*5) for i in range(40)]
    train,val,meta=h._split_by_events(rows)
    assert meta['event_count'] == 1
    assert val == []
    assert meta['event_split_overlap'] == []
    assert meta['independent_event_status'] == 'insufficient_independent_events'


def test_gap_separates_events_without_overlap(monkeypatch):
    monkeypatch.setattr(h.runtime_config, 'get', lambda name, default=None: 30 if name=='HYDRO_EVENT_GAP_MIN' else default)
    rows=[_row(1,0), _row(2,20), _row(3,80), _row(4,90), _row(5,160), _row(6,170)]
    train,val,meta=h._split_by_events(rows)
    assert meta['event_count'] == 3
    assert meta['train_event_count'] == 2
    assert meta['validation_event_count'] == 1
    assert set(r['event_id'] for r in train).isdisjoint({r['event_id'] for r in val})
