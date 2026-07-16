import json
import sqlite3

import hydro_flood_ml as h


def _paths(tmp_path, monkeypatch):
    monkeypatch.setattr(h, "HYDRO_ML_DIR", tmp_path / "ml")
    monkeypatch.setattr(h, "HYDRO_SAMPLE_DB_PATH", tmp_path / "samples.sqlite3")
    monkeypatch.setattr(h, "HYDRO_DATASET_JSONL_PATH", tmp_path / "dataset.jsonl")
    monkeypatch.setattr(h, "HYDRO_HISTORY_PATH", tmp_path / "hydro_history.jsonl")
    monkeypatch.setattr(h, "HYDRO_PENDING_SAMPLES_PATH", tmp_path / "pending.jsonl")
    monkeypatch.setattr(h, "HYDRO_DATASET_PATH", tmp_path / "legacy.jsonl")
    monkeypatch.setattr(h, "HYDRO_TRAINING_LOCK_PATH", tmp_path / "training.lock")


def test_startup_migration_is_locked_and_idempotent(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    h.HYDRO_HISTORY_PATH.write_text(json.dumps({"station_id": "A", "measured_at": "2026-01-01T00:00:00Z", "q_m3s": 2}) + "\n")
    first = h.run_hydro_startup_migrations()
    second = h.run_hydro_startup_migrations()
    with h._sample_db() as con:
        assert con.execute("SELECT COUNT(*) FROM q_history").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM schema_migrations WHERE migration_id=?", ("b417_q_history_jsonl_to_sqlite_v1",)).fetchone()[0] == 1
    assert first["q_history"]["rows_imported"] == 1
    assert second["q_history"]["already_applied"] is True


def test_materialize_without_scheduler_triggers_migration(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    called = []
    original = h.run_hydro_startup_migrations
    monkeypatch.setattr(h, "run_hydro_startup_migrations", lambda lock_handle=None: (called.append(True), original(lock_handle))[1])
    result = h.materialize_pending_samples()
    assert called == [True]
    assert result["loaded_pending"] == 0
