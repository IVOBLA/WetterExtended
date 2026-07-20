"""B432: Erkennung und verlustarmer Wiederaufbau der Sample-DB."""
import sqlite3

import pytest

import hydro_flood_ml


@pytest.fixture()
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_ML_DIR", tmp_path)
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_SAMPLE_DB_PATH", tmp_path / "hydro_flood_samples.sqlite3")
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_DATASET_JSONL_PATH", tmp_path / "hydro_flood_dataset.jsonl")
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_SAMPLE_DB_QUARANTINE_DIR", tmp_path / "quarantine")
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_SAMPLE_DB_INTEGRITY_PATH", tmp_path / "hydro_sample_db_integrity.json")
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_MAINTENANCE_STATUS_PATH", tmp_path / "maintenance.json")
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_TRAINING_LOCK_PATH", tmp_path / "training.lock")
    return tmp_path


def _seed(rows=20):
    with hydro_flood_ml._sample_db() as con:
        con.execute("BEGIN IMMEDIATE")
        for index in range(rows):
            con.execute("INSERT INTO q_history(station_id, measured_at, q_m3s) VALUES(?,?,?)",
                        ("2001049", f"2026-07-17T{index:02d}:00:00Z", 1.0 + index))
            con.execute("INSERT INTO labeled_samples(sample_id, station_id, payload) VALUES(?,?,?)",
                        (f"s{index}", "2001049", "{}"))


def test_integrity_ok_missing_noop_und_dry_run(_db, monkeypatch):
    assert hydro_flood_ml.sample_db_integrity()["integrity_status"] == "missing"
    _seed()
    assert hydro_flood_ml.sample_db_integrity()["integrity_status"] == "ok"
    assert hydro_flood_ml.repair_sample_db()["repair_status"] == "not_needed"
    monkeypatch.setattr(hydro_flood_ml, "sample_db_integrity", lambda: {"integrity_status": "corrupt"})
    assert hydro_flood_ml.repair_sample_db(dry_run=True)["repair_status"] == "would_repair"
    assert not (_db / "quarantine").exists()


def test_reparatur_rettet_zeilen_und_quarantaeniert_original(_db, monkeypatch):
    _seed(30)
    real_integrity = hydro_flood_ml.sample_db_integrity
    calls = 0

    def fake_integrity():
        nonlocal calls
        calls += 1
        return ({"integrity_status": "corrupt", "affected_tables": ["q_history"]}
                if calls == 1 else real_integrity())

    monkeypatch.setattr(hydro_flood_ml, "sample_db_integrity", fake_integrity)
    result = hydro_flood_ml.repair_sample_db()
    assert result["repair_status"] == "repaired"
    assert result["rows_copied"] >= 60
    assert result["rows_skipped"] == 0
    assert list((_db / "quarantine").glob("hydro_flood_samples.*.sqlite3"))
    assert result["integrity_after"]["integrity_status"] == "ok"
    with hydro_flood_ml._sample_db() as con:
        assert con.execute("SELECT COUNT(*) FROM q_history").fetchone()[0] == 30
        assert con.execute("SELECT COUNT(*) FROM labeled_samples").fetchone()[0] == 30


class _ExecuteProxy:
    def __init__(self, connection, replacement):
        self.connection = connection
        self.replacement = replacement

    def execute(self, sql, *params):
        return self.replacement(self.connection, sql, *params)

    def __getattr__(self, name):
        return getattr(self.connection, name)


def test_blockkopie_und_rootpage_aufloesung(_db, monkeypatch):
    _seed(10)
    source = sqlite3.connect(_db / "hydro_flood_samples.sqlite3")
    target = sqlite3.connect(":memory:")
    target.execute("CREATE TABLE q_history (station_id TEXT, measured_at TEXT, fetched_at TEXT, "
                   "q_m3s REAL, data_age_min REAL, source TEXT, PRIMARY KEY(station_id, measured_at))")

    def flaky(connection, sql, *params):
        if "SELECT" in sql and "FROM \"q_history\"" in sql and "BETWEEN" not in sql and "MIN(rowid)" not in sql:
            raise sqlite3.DatabaseError("database disk image is malformed")
        return connection.execute(sql, *params)

    result = hydro_flood_ml._copy_table_rows(_ExecuteProxy(source, flaky), target, "q_history")
    assert result == {"table": "q_history", "status": "copied_partial", "copied": 10, "skipped": 0}
    source.close()
    target.close()

    real_connect = sqlite3.connect
    rootpage = real_connect(_db / "hydro_flood_samples.sqlite3").execute(
        "SELECT rootpage FROM sqlite_master WHERE name='q_history'"
    ).fetchone()[0]

    def fake_connect(path, *args, **kwargs):
        connection = real_connect(path, *args, **kwargs)

        def fake_execute(inner, sql, *params):
            if sql == "PRAGMA quick_check":
                return [(f"Tree {rootpage} page 1 cell 0: Rowid 5 out of order",)]
            return inner.execute(sql, *params)
        return _ExecuteProxy(connection, fake_execute)

    monkeypatch.setattr(sqlite3, "connect", fake_connect)
    integrity = hydro_flood_ml.sample_db_integrity()
    assert integrity["affected_tables"] == ["q_history"]
    assert integrity["affected_rootpages"] == [rootpage]


def test_maintenance_stoppt_vor_aenderungen(_db, monkeypatch):
    _seed()
    monkeypatch.setattr(hydro_flood_ml, "sample_db_integrity",
                        lambda: {"integrity_status": "corrupt", "affected_tables": ["q_history"]})
    report = hydro_flood_ml.hydro_ml_maintenance()
    assert report["status"] == "degraded_sample_db"
    assert report["integrity_affected_tables"] == ["q_history"]
    with hydro_flood_ml._sample_db() as con:
        assert con.execute("SELECT COUNT(*) FROM q_history").fetchone()[0] == 20
