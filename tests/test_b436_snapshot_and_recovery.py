"""B436: Snapshot-Integritätscheck im Export + selbstheilender Startup + FULL-Durability.

Grundlage: KI-Report vom 2026-07-19 (vor B432). Der Export meldete den Snapshot als
"ok", obwohl integrity_check "Rowid out of order" lieferte; ein Neustart heilte die
Korruption nicht; synchronous stand auf NORMAL.
"""
import sqlite3

import pytest

import debug_export
import hydro_flood_ml


@pytest.fixture()
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_ML_DIR", tmp_path)
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_SAMPLE_DB_PATH", tmp_path / "hydro_flood_samples.sqlite3")
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_DATASET_JSONL_PATH", tmp_path / "hydro_flood_dataset.jsonl")
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_SAMPLE_DB_QUARANTINE_DIR", tmp_path / "quarantine")
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_TRAINING_LOCK_PATH", tmp_path / "training.lock")
    return tmp_path


def _seed(rows: int = 10) -> None:
    with hydro_flood_ml._sample_db() as con:
        con.execute("BEGIN IMMEDIATE")
        for i in range(rows):
            con.execute("INSERT OR IGNORE INTO q_history(station_id, measured_at, q_m3s) VALUES(?,?,?)",
                        ("2001049", f"2026-07-19T{i:02d}:00:00Z", 1.0 + i))


def test_snapshot_status_ok_bei_intakter_quelle(_db, tmp_path, monkeypatch):
    _seed()
    monkeypatch.chdir(tmp_path.parent)
    src = tmp_path.parent / "train_data" / "hydro" / "ml"
    src.mkdir(parents=True, exist_ok=True)
    (tmp_path / "hydro_flood_samples.sqlite3").replace(src / "hydro_flood_samples.sqlite3")
    _temp, _cands, status = debug_export._prepare_hydro_ml_snapshot(tmp_path.parent)
    assert status["hydro_ml_snapshot_status"] == "ok"


def test_snapshot_status_corrupt_wird_erkannt(tmp_path, monkeypatch):
    """Der eigentliche Regressionstest gegen Report-Fehler 2."""
    src_dir = tmp_path / "train_data" / "hydro" / "ml"
    src_dir.mkdir(parents=True)
    dbfile = src_dir / "hydro_flood_samples.sqlite3"
    con = sqlite3.connect(str(dbfile))
    con.execute("CREATE TABLE schema_migrations(migration_id TEXT PRIMARY KEY, applied_at TEXT)")
    con.execute("INSERT INTO schema_migrations VALUES('m1','2026-07-19')")
    con.commit(); con.close()

    real_connect = sqlite3.connect

    class _ConnectionProxy:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, sql, *params):
            if sql == "PRAGMA quick_check":
                return [("*** in database main ***",), ("Tree 3437 page 10604 cell 426: Rowid 159000 out of order",)]
            return self._connection.execute(sql, *params)

        def __getattr__(self, name):
            return getattr(self._connection, name)

    snapshot_connections = {"count": 0}

    def _fake_connect(path, *args, **kwargs):
        connection = real_connect(path, *args, **kwargs)
        if str(path).endswith("_snapshot.sqlite3"):
            snapshot_connections["count"] += 1
            if snapshot_connections["count"] == 2:
                return _ConnectionProxy(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", _fake_connect)
    _temp, cands, status = debug_export._prepare_hydro_ml_snapshot(tmp_path)
    assert status["hydro_ml_snapshot_status"] == "corrupt"
    assert "database main" in status["hydro_ml_snapshot_integrity"]
    assert status["hydro_ml_snapshot_integrity_message_count"] == 2
    assert any("snapshot" in str(c.arc_rel) for c in cands)


def test_synchronous_ist_full(_db):
    with hydro_flood_ml._sample_db() as con:
        mode = con.execute("PRAGMA synchronous").fetchone()[0]
    assert mode == 2


def test_startup_repariert_korrupte_db_automatisch(_db, monkeypatch):
    _seed(rows=20)
    calls = {"n": 0}
    real = hydro_flood_ml.sample_db_integrity

    def _fake(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] <= 2:
            return {"integrity_status": "corrupt", "affected_tables": ["q_history"],
                    "affected_rootpages": [3437], "message_count": 5}
        return real(*args, **kwargs)

    monkeypatch.setattr(hydro_flood_ml, "sample_db_integrity", _fake)
    monkeypatch.setattr(hydro_flood_ml, "migrate_pending_jsonl_to_sqlite", lambda: {})
    monkeypatch.setattr(hydro_flood_ml, "migrate_q_history_to_sqlite", lambda: {})
    monkeypatch.setattr(hydro_flood_ml, "migrate_productive_dataset", lambda: {})
    monkeypatch.setattr(hydro_flood_ml, "migrate_assign_event_ids_b421", lambda: {})

    out = hydro_flood_ml.run_hydro_startup_migrations()
    assert out["recovery"]["repair_status"] == "repaired"
    assert out["recovery"]["integrity_status"] == "corrupt"
    assert (_db / "quarantine").is_dir()
    with hydro_flood_ml._sample_db() as con:
        assert con.execute("SELECT COUNT(*) FROM q_history").fetchone()[0] == 20


def test_startup_laesst_intakte_db_unangetastet(_db, monkeypatch):
    _seed(rows=5)
    monkeypatch.setattr(hydro_flood_ml, "migrate_pending_jsonl_to_sqlite", lambda: {})
    monkeypatch.setattr(hydro_flood_ml, "migrate_q_history_to_sqlite", lambda: {})
    monkeypatch.setattr(hydro_flood_ml, "migrate_productive_dataset", lambda: {})
    monkeypatch.setattr(hydro_flood_ml, "migrate_assign_event_ids_b421", lambda: {})

    out = hydro_flood_ml.run_hydro_startup_migrations()
    assert out["recovery"]["integrity_status"] == "ok"
    assert not (_db / "quarantine").exists()


def test_recovery_fehler_bricht_startup_nicht_ab(_db, monkeypatch):
    def _boom(*args, **kwargs):
        raise sqlite3.OperationalError("disk I/O error")
    monkeypatch.setattr(hydro_flood_ml, "sample_db_integrity", _boom)
    monkeypatch.setattr(hydro_flood_ml, "migrate_pending_jsonl_to_sqlite", lambda: {"ok": True})
    monkeypatch.setattr(hydro_flood_ml, "migrate_q_history_to_sqlite", lambda: {})
    monkeypatch.setattr(hydro_flood_ml, "migrate_productive_dataset", lambda: {})
    monkeypatch.setattr(hydro_flood_ml, "migrate_assign_event_ids_b421", lambda: {})

    out = hydro_flood_ml.run_hydro_startup_migrations()
    assert out["recovery"]["integrity_status"] == "recovery_error"
    assert out["pending"] == {"ok": True}
