"""B438: Ein kaputter pending-Payload darf die Materialisierung nicht abbrechen.

Live-Traceback 2026-07-20: json.loads eines pending-Payloads lieferte einen float
(nackte Zahl statt Objekt), `float.get('station_id')` warf AttributeError und blockierte
den Endpunkt für alle Stationen — obwohl die DB nach B432-Reparatur intakt war.
"""
import json

import pytest

import hydro_flood_ml


@pytest.fixture()
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_ML_DIR", tmp_path)
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_SAMPLE_DB_PATH", tmp_path / "hydro_flood_samples.sqlite3")
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_DATASET_JSONL_PATH", tmp_path / "hydro_flood_dataset.jsonl")
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_TRAINING_LOCK_PATH", tmp_path / "training.lock")
    # Migration als angewendet markieren, damit materialize nicht in den
    # Startup-Migrationspfad abbiegt.
    with hydro_flood_ml._sample_db() as con:
        con.execute("BEGIN IMMEDIATE")
        con.execute(
            "INSERT OR REPLACE INTO schema_migrations(migration_id, applied_at) VALUES(?,?)",
            ("b417_q_history_jsonl_to_sqlite_v1", "2026-07-20T00:00:00Z"),
        )
    return tmp_path


def _insert_pending(payload_text: str, sample_id: str, created_at: str = "2020-01-01T00:00:00Z"):
    with hydro_flood_ml._sample_db() as con:
        con.execute("BEGIN IMMEDIATE")
        con.execute(
            "INSERT OR REPLACE INTO pending_samples(sample_id, station_id, sample_start_time, created_at, payload) VALUES(?,?,?,?,?)",
            (sample_id, "2001049", "2020-01-01T00:00:00Z", created_at, payload_text),
        )


def test_float_payload_bricht_nicht_ab(_db):
    """Der eigentliche Regressionstest gegen den Live-Traceback."""
    _insert_pending("3.14", "kaputt_float")
    res = hydro_flood_ml.materialize_pending_samples()          # darf NICHT werfen
    assert res["store"] == "sqlite"
    assert res.get("malformed_pending_skipped", 0) >= 1


def test_ungueltiges_json_bricht_nicht_ab(_db):
    _insert_pending("{nicht valides json", "kaputt_json")
    res = hydro_flood_ml.materialize_pending_samples()
    assert res.get("malformed_pending_skipped", 0) >= 1


def test_json_array_payload_wird_uebersprungen(_db):
    _insert_pending("[1, 2, 3]", "kaputt_array")
    res = hydro_flood_ml.materialize_pending_samples()
    assert res.get("malformed_pending_skipped", 0) >= 1


def test_kaputte_zeile_wird_entfernt(_db):
    _insert_pending("42", "kaputt_zahl")
    hydro_flood_ml.materialize_pending_samples()
    with hydro_flood_ml._sample_db() as con:
        rest = con.execute("SELECT COUNT(*) FROM pending_samples WHERE sample_id=?", ("kaputt_zahl",)).fetchone()[0]
    assert rest == 0, "Kaputte Zeile muss nach dem Lauf entfernt sein (sonst Dauerlast)"


def test_intakte_payloads_bleiben_unberuehrt(_db):
    """Ein gültiges, aber noch nicht fälliges Sample darf nicht gelöscht werden."""
    good = {"sample_id": "gut_1", "station_id": "2001049",
            "sample_start_time": "2099-01-01T00:00:00Z", "current_q_m3s": 1.0}
    _insert_pending(json.dumps(good), "gut_1", created_at="2099-01-01T00:00:00Z")
    res = hydro_flood_ml.materialize_pending_samples()
    assert res.get("malformed_pending_skipped", 0) == 0
    with hydro_flood_ml._sample_db() as con:
        rest = con.execute("SELECT COUNT(*) FROM pending_samples WHERE sample_id=?", ("gut_1",)).fetchone()[0]
    assert rest == 1, "Gültiges, nicht fälliges Sample darf nicht entfernt werden"


def test_mischung_gut_und_kaputt(_db):
    good = {"sample_id": "gut_2", "station_id": "2001049",
            "sample_start_time": "2099-01-01T00:00:00Z", "current_q_m3s": 2.0}
    _insert_pending(json.dumps(good), "gut_2", created_at="2099-01-01T00:00:00Z")
    _insert_pending("null", "kaputt_null")
    _insert_pending("1.5", "kaputt_float2")
    res = hydro_flood_ml.materialize_pending_samples()
    assert res.get("malformed_pending_skipped", 0) == 2
    with hydro_flood_ml._sample_db() as con:
        gut = con.execute("SELECT COUNT(*) FROM pending_samples WHERE sample_id=?", ("gut_2",)).fetchone()[0]
        kaputt = con.execute("SELECT COUNT(*) FROM pending_samples WHERE payload NOT LIKE '{%'").fetchone()[0]
    assert gut == 1 and kaputt == 0
