"""B431: Jede Sample-DB-Verbindung wird geschlossen.

Live-Befund 2026-07-17: 23 Aufrufstellen benutzten `with _sample_db() as con:`,
aber `sqlite3.Connection.__exit__` schließt nicht — im ganzen Modul gab es kein
`con.close()`. Drei Dienste greifen auf dieselbe WAL-DB zu; offene Leser blockieren
den Checkpoint.
"""
import sqlite3

import pytest

import hydro_flood_ml


@pytest.fixture()
def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_ML_DIR", tmp_path)
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_SAMPLE_DB_PATH", tmp_path / "hydro_flood_samples.sqlite3")
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_DATASET_JSONL_PATH", tmp_path / "hydro_flood_dataset.jsonl")
    return tmp_path


def test_verbindung_ist_nach_dem_block_geschlossen(_tmp_db):
    with hydro_flood_ml._sample_db() as con:
        con.execute("SELECT COUNT(*) FROM q_history").fetchone()
        leaked = con
    with pytest.raises(sqlite3.ProgrammingError):
        leaked.execute("SELECT 1")


def test_verbindung_wird_auch_bei_ausnahme_geschlossen(_tmp_db):
    leaked = None
    with pytest.raises(RuntimeError):
        with hydro_flood_ml._sample_db() as con:
            leaked = con
            raise RuntimeError("Abbruch im Block")
    assert leaked is not None
    with pytest.raises(sqlite3.ProgrammingError):
        leaked.execute("SELECT 1")


def test_geschriebene_daten_bleiben_nach_dem_block_erhalten(_tmp_db):
    with hydro_flood_ml._sample_db() as con:
        con.execute("BEGIN IMMEDIATE")
        con.execute("INSERT INTO q_history(station_id, measured_at, q_m3s) VALUES(?,?,?)",
                    ("2001049", "2026-07-17T21:30:00Z", 1.85))
    with hydro_flood_ml._sample_db() as con:
        row = con.execute("SELECT q_m3s FROM q_history WHERE station_id=?", ("2001049",)).fetchone()
    assert row is not None and row[0] == 1.85


def test_ausnahme_im_block_rollt_zurueck(_tmp_db):
    with pytest.raises(RuntimeError):
        with hydro_flood_ml._sample_db() as con:
            con.execute("BEGIN IMMEDIATE")
            con.execute("INSERT INTO q_history(station_id, measured_at, q_m3s) VALUES(?,?,?)",
                        ("9999999", "2026-07-17T21:30:00Z", 42.0))
            raise RuntimeError("Abbruch nach Insert")
    with hydro_flood_ml._sample_db() as con:
        row = con.execute("SELECT q_m3s FROM q_history WHERE station_id=?", ("9999999",)).fetchone()
    assert row is None


def test_open_sample_db_liefert_offene_verbindung(_tmp_db):
    con = hydro_flood_ml._open_sample_db()
    try:
        assert con.execute("SELECT 1").fetchone() == (1,)
    finally:
        con.close()


def test_keine_rohe_sample_db_verwendung_im_modul():
    """Regressionsschutz: neue Aufrufstellen müssen die with-Form benutzen."""
    import pathlib
    text = pathlib.Path("hydro_flood_ml.py").read_text(encoding="utf-8")
    calls = text.count("_sample_db()")
    with_calls = text.count("with _sample_db() as")
    # Erlaubt sind: alle with-Aufrufe + genau 1 Definitionszeile.
    assert calls - with_calls == 1, f"{calls - with_calls} rohe _sample_db()-Aufrufe ohne with"
