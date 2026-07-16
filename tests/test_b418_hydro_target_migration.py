import json
from datetime import datetime, timedelta, timezone

import hydro_flood_ml as h


def test_b418_migration_relabels_or_preserves_failure(tmp_path, monkeypatch):
    db = tmp_path / "samples.sqlite3"
    monkeypatch.setattr(h, "HYDRO_ML_DIR", tmp_path)
    monkeypatch.setattr(h, "HYDRO_SAMPLE_DB_PATH", db)
    monkeypatch.setattr(h, "HYDRO_DATASET_JSONL_PATH", tmp_path / "dataset.jsonl")
    monkeypatch.setattr(h, "HYDRO_DATASET_PATH", tmp_path / "legacy.jsonl")
    monkeypatch.setattr(h, "HYDRO_TRAINING_META_PATH", tmp_path / "meta.json")
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with h._sample_db() as con:
        for sid, q in (("covered", 9.0), ("missing", 9.0)):
            payload = {"sample_id": sid, "station_id": sid, "sample_start_time": start.isoformat(),
                       "current_q_m3s": q, "sample_kind": h.SAMPLE_KIND_LIVE,
                       "feature_schema_version": "b416_live_catchment_v4", "features": {},
                       "feature_snapshot_complete": True, "target_missing": False, "target_q_delta_m3s": -4.0}
            con.execute("INSERT INTO labeled_samples(sample_id,station_id,sample_start_time,labeled_at,payload) VALUES(?,?,?,?,?)",
                        (sid, sid, start.isoformat(), start.isoformat(), json.dumps(payload)))
        con.execute("INSERT INTO q_history(station_id,measured_at,q_m3s) VALUES(?,?,?)",
                    ("covered", (start + timedelta(minutes=30)).isoformat(), 5.0))
    first = h.migrate_productive_dataset()
    with h._sample_db() as con:
        covered = json.loads(con.execute("SELECT payload FROM labeled_samples WHERE sample_id='covered'").fetchone()[0])
        failure = con.execute("SELECT reason FROM sample_failures WHERE sample_id='missing'").fetchone()[0]
        count = con.execute("SELECT COUNT(*) FROM schema_migrations WHERE migration_id='b418_target_definition_v1'").fetchone()[0]
    assert covered["target_q_delta_m3s"] == 0.0
    assert covered["feature_schema_version"] == h.FEATURE_SCHEMA_VERSION
    assert failure == "target_definition_superseded_b418_history_unavailable"
    h.migrate_productive_dataset()
    with h._sample_db() as con:
        assert con.execute("SELECT COUNT(*) FROM schema_migrations WHERE migration_id='b418_target_definition_v1'").fetchone()[0] == count == 1
