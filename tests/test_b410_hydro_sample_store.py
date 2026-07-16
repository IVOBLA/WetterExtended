import multiprocessing as mp
import hydro_flood_ml as h

def _write(db, tmp):
    h.HYDRO_SAMPLE_DB_PATH = db
    h.HYDRO_ML_DIR = tmp
    row={k:1.0 for k in h.HYDRO_FLOOD_ML_FEATURES}
    row.update({'station_id': str(mp.current_process().pid), 'current_q_m3s':1, 'catchment_geometry_available':True, 'current_q_measured_at':'2026-01-01T00:00:00Z'})
    h.record_pending_samples([row], cells_meta={'hash':str(mp.current_process().pid)})

def test_sqlite_parallel_writers(tmp_path):
    db=tmp_path/'s.sqlite3'
    ps=[mp.Process(target=_write,args=(db,tmp_path)) for _ in range(2)]
    [p.start() for p in ps]; [p.join() for p in ps]
    assert all(p.exitcode == 0 for p in ps)
    h.HYDRO_SAMPLE_DB_PATH=db; h.HYDRO_ML_DIR=tmp_path
    assert len(h._db_rows('pending_samples')) == 2
