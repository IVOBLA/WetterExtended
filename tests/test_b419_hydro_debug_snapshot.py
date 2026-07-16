import json
import sqlite3
import zipfile
from pathlib import Path

import debug_export as d


def _db(path, count=3):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE samples(id INTEGER)")
        con.executemany("INSERT INTO samples VALUES(?)", [(i,) for i in range(count)])
        con.execute("CREATE TABLE schema_migrations(migration_id TEXT, applied_at TEXT)")
        con.execute("INSERT INTO schema_migrations VALUES('b418','now')")


def test_backup_snapshot_is_consistent_and_temp_is_removed(tmp_path):
    source = tmp_path / "train_data/hydro/ml/hydro_flood_samples.sqlite3"
    _db(source)
    temp, candidates, status = d._prepare_hydro_ml_snapshot(tmp_path)
    snap = next(c.src for c in candidates if c.src.name == "hydro_flood_samples_snapshot.sqlite3")
    assert status["hydro_ml_snapshot_status"] == "ok"
    assert not snap.is_relative_to(tmp_path / "train_data/hydro/ml")
    con = sqlite3.connect(snap)
    try:
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert con.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 3
    finally:
        con.close()
    assert not Path(str(snap) + "-wal").exists()
    import shutil
    shutil.rmtree(temp)


def test_export_contains_snapshot_not_live_db_and_cleans_temp(monkeypatch, tmp_path):
    source = tmp_path / "train_data/hydro/ml/hydro_flood_samples.sqlite3"
    _db(source)
    for rel in ("train_data/hydro/ml/hydro_flood_training_meta.json", "train_data/models/hydro_flood/current/metadata.json", "train_data/models/hydro_flood/current/manifest.json", "train_data/hydro/ml/hydro_ml_maintenance_latest.json"):
        p = tmp_path / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text("{}")
    monkeypatch.setattr(d, "run_forecast_quality_diagnosis_before_export", lambda **k: {})
    monkeypatch.setattr(d, "run_kinematic_acceleration_diagnosis_before_export", lambda **k: {})
    monkeypatch.setattr(d, "run_convlstm_training_diagnosis_before_export", lambda **k: {})
    made = []
    original = d._prepare_hydro_ml_snapshot
    def tracked(base):
        result = original(base); made.append(result[0]); return result
    monkeypatch.setattr(d, "_prepare_hydro_ml_snapshot", tracked)
    out, _, manifest = d.create_debug_export_zip(base_dir=tmp_path, tmp_path=tmp_path / "out.zip")
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert any(n.endswith("hydro_flood_samples_snapshot.sqlite3") for n in names)
        assert not any(n.endswith("/hydro_flood_samples.sqlite3") or n.endswith("-wal") or n.endswith("-shm") for n in names)
        for name in ("hydro_flood_training_meta.json", "metadata.json", "manifest.json", "schema_migrations.json", "hydro_ml_maintenance_latest.json"):
            assert any(n.endswith(name) for n in names)
    assert manifest["hydro_ml_snapshot_status"] == "ok"
    assert all(not p.exists() for p in made)


def test_backup_error_has_status_and_no_fallback(monkeypatch, tmp_path):
    source = tmp_path / "train_data/hydro/ml/hydro_flood_samples.sqlite3"; _db(source)
    original = d.sqlite3.connect
    calls = 0
    def failing_connect(path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise sqlite3.Error("boom")
        return original(path)
    monkeypatch.setattr(d.sqlite3, "connect", failing_connect)
    temp, candidates, status = d._prepare_hydro_ml_snapshot(tmp_path)
    assert status["hydro_ml_snapshot_status"] == "error"
    assert "boom" in status["hydro_ml_snapshot_error"]
    assert not any(c.src.name == "hydro_flood_samples_snapshot.sqlite3" for c in candidates)
    import shutil; shutil.rmtree(temp)


def test_snapshot_over_limit_is_reported(monkeypatch, tmp_path):
    source = tmp_path / "train_data/hydro/ml/hydro_flood_samples.sqlite3"; _db(source)
    monkeypatch.setattr(d, "EXPORT_VOLUME_MAX_BYTES", 1)
    temp, candidates, status = d._prepare_hydro_ml_snapshot(tmp_path)
    assert status["hydro_ml_snapshot_status"] == "omitted_size_limit"
    assert status["hydro_ml_snapshot_size_bytes"] > status["hydro_ml_snapshot_limit_bytes"]
    import shutil; shutil.rmtree(temp)
