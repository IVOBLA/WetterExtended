"""B445: Echte Einfuegungen zaehlen und mehrzeilige DB-Fehler auswerten."""

import sqlite3

import pytest

import hydro_flood_ml


def test_ignore_verletzung_zaehlt_als_skipped():
    src = sqlite3.connect(":memory:")
    dst = sqlite3.connect(":memory:")
    src.execute("CREATE TABLE q_history (station_id TEXT, measured_at TEXT, q_m3s REAL)")
    dst.execute(
        "CREATE TABLE q_history (station_id TEXT NOT NULL, measured_at TEXT NOT NULL, "
        "q_m3s REAL, PRIMARY KEY(station_id, measured_at))"
    )
    src.executemany(
        "INSERT INTO q_history VALUES(?,?,?)",
        [("A", "t1", 1.0), (None, "t2", 2.0), ("B", None, 3.0)],
    )

    result = hydro_flood_ml._copy_table_rows(src, dst, "q_history")

    assert result["copied"] == 1
    assert result["skipped"] == 2
    assert dst.execute("SELECT COUNT(*) FROM q_history").fetchone()[0] == result["copied"]


def test_saubere_kopie_meldet_kein_skip():
    src = sqlite3.connect(":memory:")
    dst = sqlite3.connect(":memory:")
    for connection in (src, dst):
        connection.execute(
            "CREATE TABLE q_history (station_id TEXT NOT NULL, measured_at TEXT NOT NULL, "
            "q_m3s REAL, PRIMARY KEY(station_id, measured_at))"
        )
    src.executemany(
        "INSERT INTO q_history VALUES(?,?,?)", [("A", "t1", 1.0), ("A", "t2", 2.0)]
    )

    result = hydro_flood_ml._copy_table_rows(src, dst, "q_history")

    assert result["copied"] == 2
    assert result["skipped"] == 0


@pytest.fixture()
def sample_db(tmp_path, monkeypatch):
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_ML_DIR", tmp_path)
    monkeypatch.setattr(
        hydro_flood_ml, "HYDRO_SAMPLE_DB_PATH", tmp_path / "hydro_flood_samples.sqlite3"
    )
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_DATASET_JSONL_PATH", tmp_path / "d.jsonl")
    return tmp_path


def test_mehrzeilige_quick_check_message_findet_tabelle(sample_db, monkeypatch):
    with hydro_flood_ml._sample_db() as connection:
        rootpage = connection.execute(
            "SELECT rootpage FROM sqlite_master WHERE name='q_history'"
        ).fetchone()[0]
    real_connect = sqlite3.connect

    class QuickCheckConnection:
        def __init__(self, path, *args, **kwargs):
            self.connection = real_connect(path, *args, **kwargs)

        def execute(self, sql, parameters=()):
            if sql == "PRAGMA quick_check":
                return [(
                    f"*** in database main ***\nTree {rootpage} page 10 cell 1: "
                    f"Rowid out of order\nTree {rootpage} page 11 cell 2: Rowid out of order",
                )]
            return self.connection.execute(sql, parameters)

        def close(self):
            self.connection.close()

    monkeypatch.setattr(sqlite3, "connect", QuickCheckConnection)
    result = hydro_flood_ml.sample_db_integrity()

    assert result["integrity_status"] == "corrupt"
    assert result["affected_tables"] == ["q_history"]
    assert rootpage in result["affected_rootpages"]
