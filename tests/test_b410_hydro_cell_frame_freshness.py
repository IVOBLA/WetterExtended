import json
from datetime import datetime, timezone, timedelta
import hydro_flood_ml as h

def test_stale_cell_frame_deferred(tmp_path, monkeypatch):
    obj=tmp_path/'objects'; obj.mkdir()
    old=(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()
    (obj/'frame.json').write_text(json.dumps({'generated_at':old,'objects':[]}), encoding='utf-8')
    monkeypatch.setitem(h.config.SAVE_PATHS, 'objects', str(obj))
    monkeypatch.setattr(h.runtime_config, 'get', lambda name, default=None: 30 if name=='HYDRO_CELL_FRAME_MAX_AGE_MIN' else default)
    cells, meta=h.load_latest_cell_frame()
    assert cells is None
    assert meta['status'] == 'stale'
