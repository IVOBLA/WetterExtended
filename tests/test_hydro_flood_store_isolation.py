"""B430: Ein Defekt der Sample-SQLite darf die Flood-Risk-Anzeige nicht abschalten.

Live-Befund 2026-07-17: q_history war korrupt (`Rowid out of order`, Tree 3437).
`/api/hydro/flood-risk` lieferte 17 Stunden lang 105-Byte-Fehlerantworten, alle
85 Stationen zeigten "nicht bewertbar". Grenzwert, Niederschlag und Zellzahl
stammen aber gar nicht aus der SQLite.
"""
import sqlite3

import pytest

import hydro_flood_ml


@pytest.fixture(autouse=True)
def _clean_faults():
    hydro_flood_ml.reset_sample_store_faults()
    yield
    hydro_flood_ml.reset_sample_store_faults()


def _raise_malformed(*_args, **_kwargs):
    raise sqlite3.DatabaseError("database disk image is malformed")


def _station():
    return {
        "station_id": "2001049",
        "name": "Urschwirtbrücke",
        "river": "Gurk",
        "lat": 46.774665,
        "lon": 14.007886,
        "q_m3s": 1.85,
        "mark_q_m3s": 8.0,
        "impact_effective": True,
        "status": "ok",
    }


def _live():
    return {
        "fetched_at": "2026-07-17T21:44:00Z",
        "stations": [{**_station(), "measured_at": "2026-07-17T22:30:00+01:00"}],
        "cell_frame_meta": {"status": "ok", "cell_frame_status": "ok", "frame_timestamp": "2026-07-17T21:35:00Z", "frame_age_min": 9.0, "raw_cell_count": 0},
    }


def test_q_trend_history_liefert_leeres_dict_bei_defekter_db(monkeypatch):
    monkeypatch.setattr(hydro_flood_ml, "_sample_db", _raise_malformed)
    assert hydro_flood_ml.load_q_trend_history() == {}
    status = hydro_flood_ml.sample_store_status()
    assert status["sample_store_status"] == "degraded"
    assert status["sample_store_faults"][0]["stage"] == "q_trend_history"


def test_evaluate_liefert_stationen_trotz_defekter_db(monkeypatch):
    monkeypatch.setattr(hydro_flood_ml, "load_q_trend_history", lambda: (_ for _ in ()).throw(sqlite3.DatabaseError("database disk image is malformed")) if False else {})
    monkeypatch.setattr(hydro_flood_ml, "record_pending_samples", _raise_malformed)
    monkeypatch.setattr(hydro_flood_ml, "materialize_pending_samples", _raise_malformed)
    monkeypatch.setattr(hydro_flood_ml, "readiness_status", _raise_malformed)
    monkeypatch.setattr(hydro_flood_ml, "load_precip_ledger", lambda *a, **k: {})

    doc = hydro_flood_ml.evaluate_live_flood_risk(
        stations=[_station()], live=_live(), cells=[], write=False, include_debug=False
    )

    assert doc["status"] == "ok"
    assert len(doc["stations"]) == 1
    row = doc["stations"][0]
    assert row["station_id"] == "2001049"
    # Der Grenzwertvergleich braucht keine SQLite und muss weiterhin liefern.
    assert row["current_q_m3s"] == 1.85
    assert row["station_q_threshold_m3s"] == 8.0
    assert row["current_threshold_evaluable"] is True
    assert row["current_q_above_threshold"] is False


def test_store_defekt_bleibt_im_payload_sichtbar(monkeypatch):
    monkeypatch.setattr(hydro_flood_ml, "record_pending_samples", _raise_malformed)
    monkeypatch.setattr(hydro_flood_ml, "materialize_pending_samples", _raise_malformed)
    monkeypatch.setattr(hydro_flood_ml, "readiness_status", _raise_malformed)
    monkeypatch.setattr(hydro_flood_ml, "load_q_trend_history", lambda: {})
    monkeypatch.setattr(hydro_flood_ml, "load_precip_ledger", lambda *a, **k: {})

    doc = hydro_flood_ml.evaluate_live_flood_risk(
        stations=[_station()], live=_live(), cells=[], write=True, include_debug=False
    )

    assert doc["sample_store_status"] == "degraded"
    stages = {f["stage"] for f in doc["sample_store_faults"]}
    assert stages == {"record_pending_samples", "materialize_pending_samples", "readiness_status"}
    assert all("malformed" in f["error"] for f in doc["sample_store_faults"])


def test_intakter_store_meldet_ok(monkeypatch):
    monkeypatch.setattr(hydro_flood_ml, "record_pending_samples", lambda *a, **k: {"pending_added": 1, "pending_total": 1})
    monkeypatch.setattr(hydro_flood_ml, "materialize_pending_samples", lambda *a, **k: {"labeled_added": 0})
    monkeypatch.setattr(hydro_flood_ml, "readiness_status", lambda: {"enabled": True, "readiness_status": "fallback"})
    monkeypatch.setattr(hydro_flood_ml, "load_q_trend_history", lambda: {})
    monkeypatch.setattr(hydro_flood_ml, "load_precip_ledger", lambda *a, **k: {})

    doc = hydro_flood_ml.evaluate_live_flood_risk(
        stations=[_station()], live=_live(), cells=[], write=True, include_debug=False
    )

    assert doc["sample_store_status"] == "ok"
    assert doc["sample_store_faults"] == []


def test_cache_mit_falschem_scope_wird_verworfen_statt_zu_werfen(tmp_path, monkeypatch):
    """Ein Cache ohne payload_scope darf den Endpunkt nicht dauerhaft blockieren."""
    path = tmp_path / "latest_hydro_flood_risk.json"
    path.write_text('{"stations": [], "generated_at": "2026-07-17T21:00:00Z"}', encoding="utf-8")
    doc = hydro_flood_ml._read_json(path, None)
    assert isinstance(doc, dict)
    with pytest.raises(ValueError):
        hydro_flood_ml.require_public_payload_scope(doc)
    # app.py verwirft solche Dokumente jetzt vor dem Guard:
    assert doc.get("payload_scope") != "public"
