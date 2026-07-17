"""P74: Persistenz des gemessenen Zellniederschlags je Einzugsgebiet."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

hydro_flood_ml = pytest.importorskip("hydro_flood_ml")


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_ML_DIR", tmp_path, raising=False)
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_SAMPLE_DB_PATH", tmp_path / "hydro_flood_samples.sqlite3", raising=False)
    monkeypatch.setattr(hydro_flood_ml, "_DEFAULT_HYDRO_SAMPLE_DB_PATH", tmp_path / "hydro_flood_samples.sqlite3", raising=False)
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_DATASET_JSONL_PATH", tmp_path / "hydro_flood_dataset.jsonl", raising=False)
    monkeypatch.setattr(hydro_flood_ml, "_DEFAULT_HYDRO_DATASET_JSONL_PATH", tmp_path / "hydro_flood_dataset.jsonl", raising=False)
    return tmp_path


def _entry(cell_id="c1", rate=12.0, area=4.0):
    return {"station_id": "9001", "cell_id": cell_id, "eff_overlap_area_km2": area,
            "rain_rate_mm_h": rate, "rain_rate_source": "nowcast_rain_rate_1h",
            "runoff_coeff": 0.4, "raw_delta_q_m3s": round(0.4 * rate * area / 3.6, 5)}


def _rows():
    with hydro_flood_ml._sample_db() as con:
        return list(con.execute("SELECT station_id,frame_timestamp,cell_id,raw_delta_q_m3s FROM catchment_precip_ledger ORDER BY frame_timestamp,cell_id"))


def test_ledger_table_exists(db):
    with hydro_flood_ml._sample_db() as con:
        names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "catchment_precip_ledger" in names


def test_append_writes_rows(db):
    meta = hydro_flood_ml.append_precip_ledger([_entry()], "2026-07-17T12:00:00Z")
    assert meta["ledger_status"] == "ok" and meta["ledger_rows_written"] == 1
    assert _rows() == [("9001", "2026-07-17T12:00:00Z", "c1", pytest.approx(5.333, abs=0.01))]


def test_repeated_run_on_same_frame_is_idempotent(db):
    for _ in range(3):
        hydro_flood_ml.append_precip_ledger([_entry()], "2026-07-17T12:00:00Z")
    assert len(_rows()) == 1, "Doppelzählung: derselbe Frame darf nur eine Zeile je Zelle erzeugen"


def test_distinct_frames_accumulate(db):
    hydro_flood_ml.append_precip_ledger([_entry()], "2026-07-17T12:00:00Z")
    hydro_flood_ml.append_precip_ledger([_entry()], "2026-07-17T12:05:00Z")
    assert len(_rows()) == 2


def test_missing_frame_timestamp_writes_nothing(db):
    meta = hydro_flood_ml.append_precip_ledger([_entry()], None)
    assert meta["ledger_status"] == "frame_timestamp_missing" and _rows() == []


def test_disabled_writes_nothing(db, monkeypatch):
    monkeypatch.setattr(hydro_flood_ml, "ledger_enabled", lambda: False)
    meta = hydro_flood_ml.append_precip_ledger([_entry()], "2026-07-17T12:00:00Z")
    assert meta["ledger_status"] == "disabled" and _rows() == []


def test_retention_defaults_to_upper_lag_bound(db, monkeypatch):
    monkeypatch.setattr(hydro_flood_ml, "_lag_bounds_min", lambda: (20.0, 180.0))
    monkeypatch.setattr(hydro_flood_ml.runtime_config, "get", lambda k, d=None: d)
    assert hydro_flood_ml.ledger_retention_min() == 180


def test_purge_removes_only_expired_frames(db, monkeypatch):
    monkeypatch.setattr(hydro_flood_ml, "ledger_retention_min", lambda: 180)
    now = datetime(2026, 7, 17, 15, 0, tzinfo=timezone.utc)
    fresh = (now - timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
    stale = (now - timedelta(minutes=400)).isoformat().replace("+00:00", "Z")
    hydro_flood_ml.append_precip_ledger([_entry(cell_id="fresh")], fresh)
    hydro_flood_ml.append_precip_ledger([_entry(cell_id="stale")], stale)
    assert hydro_flood_ml.purge_precip_ledger(now=now) == 1
    assert [r[2] for r in _rows()] == ["fresh"]


def test_public_payload_has_no_ledger_key(db):
    row = {"station_id": "9001", "precip_ledger_t0": [_entry()], "generated_at": "x"}
    assert "precip_ledger_t0" not in hydro_flood_ml._public_flood_row(row)
