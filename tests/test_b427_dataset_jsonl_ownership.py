import json

import hydro_flood_ml as h
import pytest


@pytest.fixture
def isolated_dataset(monkeypatch, tmp_path):
    monkeypatch.setattr(h, "HYDRO_ML_DIR", tmp_path)
    monkeypatch.setattr(h, "HYDRO_SAMPLE_DB_PATH", tmp_path / "samples.sqlite3")
    monkeypatch.setattr(h, "HYDRO_DATASET_JSONL_PATH", tmp_path / "dataset.jsonl")
    monkeypatch.setattr(h, "HYDRO_DATASET_PATH", tmp_path / "legacy.jsonl")
    return tmp_path


def _sample(sample_id="sample-1"):
    return {
        "sample_id": sample_id,
        "station_id": "S1",
        "sample_start_time": "2026-01-01T00:00:00Z",
        "sample_kind": h.SAMPLE_KIND_LIVE,
        "feature_schema_version": h.FEATURE_SCHEMA_VERSION,
        "feature_schema_hash": h._feature_schema_hash(),
        "feature_snapshot_complete": True,
        "target_missing": False,
        "target_q_delta_m3s": 1.0,
        "features": {name: 1.0 for name in h.HYDRO_FLOOD_ML_FEATURES},
    }


def _insert_sample(row):
    with h._sample_db() as con:
        con.execute(
            "INSERT INTO labeled_samples(sample_id,station_id,sample_start_time,labeled_at,payload,"
            "sample_kind,feature_schema_version,feature_schema_hash,feature_snapshot_complete,"
            "target_missing,target_q_delta_m3s,event_id,cell_frame_hash,precip_event_active) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (row["sample_id"], row["station_id"], row["sample_start_time"], row["sample_start_time"],
             json.dumps(row), *h._labeled_values(row)),
        )


def _rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_export_follows_runtime_patched_default(isolated_dataset):
    _insert_sample(_sample())
    result = h.export_labeled_samples_jsonl()
    assert result["path"] == str(h.HYDRO_DATASET_JSONL_PATH)
    assert _rows(h.HYDRO_DATASET_JSONL_PATH)[0]["sample_id"] == "sample-1"


def test_export_explicit_path_takes_precedence(isolated_dataset):
    _insert_sample(_sample())
    explicit = isolated_dataset / "explicit.jsonl"
    result = h.export_labeled_samples_jsonl(explicit)
    assert result["path"] == str(explicit)
    assert _rows(explicit)[0]["sample_id"] == "sample-1"
    assert not h.HYDRO_DATASET_JSONL_PATH.exists()


def test_empty_migration_source_does_not_erase_snapshot(isolated_dataset):
    _insert_sample(_sample())
    h.HYDRO_DATASET_JSONL_PATH.write_text("", encoding="utf-8")
    h.migrate_productive_dataset()
    assert [row["sample_id"] for row in _rows(h.HYDRO_DATASET_JSONL_PATH)] == ["sample-1"]


def test_migration_exports_sqlite_samples(isolated_dataset):
    _insert_sample(_sample())
    h.migrate_productive_dataset()
    assert len(_rows(h.HYDRO_DATASET_JSONL_PATH)) == 1


def test_nonempty_source_migrates_live_and_moves_legacy(isolated_dataset):
    live = _sample("live")
    legacy = {"sample_id": "legacy", "sample_kind": h.SAMPLE_KIND_LEGACY}
    h.HYDRO_DATASET_JSONL_PATH.write_text(
        "\n".join(json.dumps(row) for row in (live, legacy)) + "\n", encoding="utf-8"
    )
    result = h.migrate_productive_dataset()
    assert result["rows_live_kept"] == 1
    assert result["rows_legacy_moved"] == 1
    assert [row["sample_id"] for row in _rows(h.HYDRO_DATASET_JSONL_PATH)] == ["live"]
    assert _rows(h.HYDRO_DATASET_PATH)[0]["sample_id"] == "legacy"


def test_second_migration_leaves_file_unchanged(isolated_dataset):
    _insert_sample(_sample())
    h.migrate_productive_dataset()
    before = h.HYDRO_DATASET_JSONL_PATH.read_bytes()
    result = h.migrate_productive_dataset()
    assert result["already_applied"] is True
    assert h.HYDRO_DATASET_JSONL_PATH.read_bytes() == before


def test_migration_payload_records_ownership_transfer(isolated_dataset):
    h.migrate_productive_dataset()
    with h._sample_db() as con:
        payload = json.loads(con.execute(
            "SELECT payload FROM schema_migrations WHERE migration_id='b410_jsonl_to_sqlite_v1'"
        ).fetchone()[0])
    assert payload["jsonl_ownership_transferred_to_export"] is True


def test_export_migration_export_order_loses_no_sample(isolated_dataset):
    _insert_sample(_sample())
    h.export_labeled_samples_jsonl()
    h.migrate_productive_dataset()
    h.export_labeled_samples_jsonl()
    assert [row["sample_id"] for row in _rows(h.HYDRO_DATASET_JSONL_PATH)] == ["sample-1"]


def test_dataset_scan_exports_labeled_sample(isolated_dataset):
    _insert_sample(_sample())
    status = h.build_dataset_scan()
    assert status["sample_count"] >= 1
    assert len(_rows(h.HYDRO_DATASET_JSONL_PATH)) >= 1
