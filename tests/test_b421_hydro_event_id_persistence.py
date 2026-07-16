import json
from datetime import datetime, timedelta, timezone

import hydro_flood_ml as h


def _iso(minutes):
    return (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def _environment(monkeypatch, tmp_path):
    monkeypatch.setattr(h, "HYDRO_ML_DIR", tmp_path)
    monkeypatch.setattr(h, "HYDRO_SAMPLE_DB_PATH", tmp_path / "samples.sqlite3")
    monkeypatch.setattr(h, "HYDRO_DATASET_JSONL_PATH", tmp_path / "samples.jsonl")
    monkeypatch.setattr(h, "HYDRO_HISTORY_PATH", tmp_path / "history.jsonl")
    monkeypatch.setattr(h, "HYDRO_TRAINING_META_PATH", tmp_path / "training.json")
    monkeypatch.setattr(h, "HYDRO_RISK_PATH", tmp_path / "risk.json")
    monkeypatch.setattr(h, "MIN_TRAINING_SAMPLES", 1)
    monkeypatch.setattr(h, "HYDRO_REQUIRED_FEATURES", [])
    h._READINESS_CACHE.clear()
    for name, value in {"HYDRO_FORECAST_SAMPLE_INTERVAL_MIN": 1, "HYDRO_LAG_WINDOW_MIN": [20, 180], "HYDRO_ML_MIN_TRAIN_EVENTS": 1, "HYDRO_ML_MIN_VALIDATION_EVENTS": 1}.items():
        monkeypatch.setattr(h.config, name, value, raising=False)


def _productive_sample(monkeypatch, minute, lineage, active=True):
    diagnostics = [{"cell_id": "cell-1", "lineage_id": lineage}] if active else []
    monkeypatch.setattr(h, "_precip_from_cells", lambda station, cells: {
        "cell_diagnostics": diagnostics, "contributing_cell_count": len(diagnostics),
        "cell_catchment_count": len(diagnostics), "cell_precip_source_type": "cell_derived" if active else "none",
        "cell_catchment_precip_sum_mm": 1.0 if active else 0.0,
        "cell_catchment_precip_weighted_sum_mm": 1.0 if active else 0.0,
        "cell_catchment_max_intensity": 2.0 if active else 0.0,
        "precip_evaluable_by_geometry": True, "precip_status": "cell_derived" if active else "no_relevant_cell",
        "precip_status_label": "test", "catchment_geometry_available": True,
        "catchment_geometry_status": "ok", "catchment_area_geometry_km2": 1.0,
    })
    measured = _iso(minute)
    with h._sample_db() as con:
        con.execute("INSERT OR REPLACE INTO q_history(station_id,measured_at,q_m3s) VALUES(?,?,?)", ("station-1", _iso(minute + 30), 2.0))
    station = {"station_id": "station-1", "q_m3s": 1.0, "measured_at": measured, "catchment_area_km2": 1.0}
    cell = {"id": "cell-1", "lineage_id": lineage, "contour_geo": [[0, 0], [0, 1], [1, 1], [0, 0]]}
    h.evaluate_live_flood_risk(stations=[station], live={"fetched_at": measured}, cells=[cell], write=True)


def _stored_events():
    with h._sample_db() as con:
        return [(event, json.loads(payload)) for event, payload in con.execute("SELECT event_id,payload FROM labeled_samples ORDER BY sample_start_time")]


def test_productive_path_persists_stable_event_and_start(monkeypatch, tmp_path):
    _environment(monkeypatch, tmp_path)
    _productive_sample(monkeypatch, 0, "lineage-a")
    _productive_sample(monkeypatch, 10, "lineage-a")
    rows = _stored_events()
    assert len(rows) == 2
    assert rows[0][0] == rows[1][0] == rows[0][1]["event_id"] == rows[1][1]["event_id"]
    assert rows[0][1]["event_start_time"] == rows[1][1]["event_start_time"] == _iso(0)
    first_id = rows[0][0]
    h.materialize_pending_samples()
    assert _stored_events()[0][0] == first_id


def test_productive_splits_gap_dry_gap_and_active_lineage(monkeypatch, tmp_path):
    _environment(monkeypatch, tmp_path)
    monkeypatch.setattr(h.config, "HYDRO_EVENT_GAP_MIN", 40, raising=False)
    monkeypatch.setattr(h.config, "HYDRO_EVENT_DRY_GAP_MIN", 15, raising=False)
    _productive_sample(monkeypatch, 0, "lineage-a")
    _productive_sample(monkeypatch, 50, "lineage-a")
    _productive_sample(monkeypatch, 60, "lineage-a", active=False)
    _productive_sample(monkeypatch, 80, "lineage-a")
    _productive_sample(monkeypatch, 90, "lineage-b")
    ids = [row[0] for row in _stored_events()]
    assert len(set(ids)) == 4


def test_readiness_counts_column_without_json_deserialization(monkeypatch, tmp_path):
    _environment(monkeypatch, tmp_path)
    monkeypatch.setattr(h.config, "HYDRO_EVENT_GAP_MIN", 15, raising=False)
    for minute in (0, 20):
        _productive_sample(monkeypatch, minute, "lineage-a")
    calls = 0
    original = h.json.loads
    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)
    monkeypatch.setattr(h.json, "loads", counted)
    status = h.readiness_status()
    assert calls == 0
    assert status["event_count"] == 2
    assert "insufficient_independent_events" not in status["rejection_reasons"]
    rows = h.load_trainable_labeled_samples(False)
    assert h.analyze_training_dataset(rows)["event_count"] == status["event_count"]


def test_migration_is_batched_and_idempotent(monkeypatch, tmp_path):
    _environment(monkeypatch, tmp_path)
    monkeypatch.setattr(h.config, "HYDRO_ML_MATERIALIZE_BATCH_SIZE", 10, raising=False)
    with h._sample_db() as con:
        for minute in range(100):
            payload = {"sample_id": f"legacy-{minute}", "station_id": "station-1", "sample_start_time": _iso(minute), "precip_event_active": True, "contributing_lineage_ids": ["lineage-a"]}
            con.execute("INSERT INTO labeled_samples(sample_id,station_id,sample_start_time,labeled_at,payload) VALUES(?,?,?,?,?)", (payload["sample_id"], payload["station_id"], payload["sample_start_time"], _iso(minute), json.dumps(payload)))
    first = h.migrate_assign_event_ids_b421()
    assert first["rows_imported"] == 10 and first["rows_remaining"] == 90
    for _ in range(9):
        last = h.migrate_assign_event_ids_b421()
    assert last["rows_remaining"] == 0
    assert h.migrate_assign_event_ids_b421()["already_applied"] is True
    with h._sample_db() as con:
        assert con.execute("SELECT COUNT(*) FROM labeled_samples WHERE event_id IS NULL").fetchone()[0] == 0
