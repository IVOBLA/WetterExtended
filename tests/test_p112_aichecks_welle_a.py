"""P112 — Welle A: fuenf ACs deterministisch migriert (AC-030, AC-031, AC-050,
AC-074, AC-079).

Jeder Check bekommt einen positiven und mindestens einen negativen Fall mit
strukturell realen Fixtures (Feldnamen 1:1 aus hydro_flood_ml.py, main.py,
tools/ro_query.py uebernommen).
"""
import json
import sqlite3
from pathlib import Path

from tools.ai_checks.checks_local import (
    check_ac030_public_payload_leak as ac030,
    check_ac031_sqlite_snapshot_consistency as ac031,
    check_ac050_dataset_export_vs_sqlite as ac050,
    check_ac074_cell_id_uniqueness_per_frame as ac074,
    check_ac079_exposed_credential_copies as ac079,
)


# ---------------------------------------------------------------------------
# AC-030 — interne Felder im oeffentlichen Payload
# ---------------------------------------------------------------------------

def _write_risk_doc(tmp_path, doc):
    d = tmp_path / "train_data" / "hydro" / "impact"
    d.mkdir(parents=True, exist_ok=True)
    (d / "latest_hydro_flood_risk.json").write_text(json.dumps(doc), encoding="utf-8")


def test_ac030_ok_no_file(tmp_path):
    r = ac030(tmp_path)
    assert r["status"] == "ok"


def test_ac030_ok_clean_public_payload(tmp_path):
    _write_risk_doc(tmp_path, {
        "payload_scope": "public",
        "stations": [
            {"station_id": "S1", "current_q_m3s": 3.2, "flood_expected": False},
            {"station_id": "S2", "current_q_m3s": 1.1, "flood_expected": True},
        ],
    })
    r = ac030(tmp_path)
    assert r["status"] == "ok"


def test_ac030_finding_forbidden_field_in_station_row(tmp_path):
    _write_risk_doc(tmp_path, {
        "payload_scope": "public",
        "stations": [{"station_id": "S1", "model_signature": "abc123"}],
    })
    r = ac030(tmp_path)
    assert r["status"] == "finding"
    assert "model_signature" in r["beleg"]


def test_ac030_finding_wrong_payload_scope(tmp_path):
    _write_risk_doc(tmp_path, {"payload_scope": "admin_diagnostics", "stations": []})
    r = ac030(tmp_path)
    assert r["status"] == "finding"
    assert "payload_scope" in r["beleg"]


def test_ac030_finding_top_level_leak(tmp_path):
    _write_risk_doc(tmp_path, {
        "payload_scope": "public", "stations": [], "hydro_flood_risk_score": 0.8,
    })
    r = ac030(tmp_path)
    assert r["status"] == "finding"
    assert "hydro_flood_risk_score" in r["beleg"]


# ---------------------------------------------------------------------------
# AC-031 — SQLite-Snapshot-Integritaet
# ---------------------------------------------------------------------------

def _make_snapshot(path, valid=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    if valid:
        con = sqlite3.connect(str(path))
        con.execute("CREATE TABLE labeled_samples(sample_id TEXT)")
        con.commit()
        con.close()
    else:
        path.write_bytes(b"kein sqlite header")


def test_ac031_ok_no_snapshot(tmp_path):
    r = ac031(tmp_path)
    assert r["status"] == "ok"


def test_ac031_ok_clean_snapshot(tmp_path):
    _make_snapshot(tmp_path / "hydro_ml" / "hydro_flood_samples_snapshot.sqlite3")
    r = ac031(tmp_path)
    assert r["status"] == "ok"


def test_ac031_finding_corrupt_snapshot(tmp_path):
    _make_snapshot(tmp_path / "hydro_ml" / "hydro_flood_samples_snapshot.sqlite3", valid=False)
    r = ac031(tmp_path)
    assert r["status"] == "finding"
    assert "integrity_check" in r["beleg"]


def test_ac031_finding_stray_live_copy(tmp_path):
    snap = tmp_path / "hydro_ml" / "hydro_flood_samples_snapshot.sqlite3"
    _make_snapshot(snap)
    stray = tmp_path / "hydro_ml" / "train_data" / "hydro" / "ml" / "hydro_flood_samples.sqlite3"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_bytes(b"unkoordinierte kopie")
    r = ac031(tmp_path)
    assert r["status"] == "finding"
    assert "unkoordinierte Kopie" in r["beleg"]


def test_ac031_finding_stray_wal_file(tmp_path):
    snap = tmp_path / "hydro_ml" / "hydro_flood_samples_snapshot.sqlite3"
    _make_snapshot(snap)
    (tmp_path / "hydro_ml" / "hydro_flood_samples.sqlite3-wal").write_bytes(b"wal")
    r = ac031(tmp_path)
    assert r["status"] == "finding"


# ---------------------------------------------------------------------------
# AC-050 — JSONL-Export gegen SQLite-Snapshot
# ---------------------------------------------------------------------------

def _make_dataset(tmp_path, jsonl_lines, db_row_count):
    d = tmp_path / "hydro_ml"
    d.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(d / "hydro_flood_samples_snapshot.sqlite3"))
    con.execute("CREATE TABLE labeled_samples(sample_id TEXT)")
    con.executemany("INSERT INTO labeled_samples VALUES (?)",
                     [(f"s{i}",) for i in range(db_row_count)])
    con.commit()
    con.close()
    with open(d / "hydro_flood_dataset.jsonl", "w", encoding="utf-8") as f:
        for line in jsonl_lines:
            f.write(line + "\n")


def test_ac050_ok_no_files(tmp_path):
    r = ac050(tmp_path)
    assert r["status"] == "ok"


def test_ac050_ok_matching_row_counts(tmp_path):
    _make_dataset(tmp_path, ['{"sample_id":"s0"}', '{"sample_id":"s1"}'], db_row_count=2)
    r = ac050(tmp_path)
    assert r["status"] == "ok"
    assert r["detail"]["jsonl_rows"] == 2


def test_ac050_finding_mismatch(tmp_path):
    _make_dataset(tmp_path, ['{"sample_id":"s0"}'], db_row_count=5)
    r = ac050(tmp_path)
    assert r["status"] == "finding"
    assert "jsonl_rows=1" in r["beleg"]
    assert "db_rows=5" in r["beleg"]


def test_ac050_finding_empty_jsonl_with_filled_db(tmp_path):
    _make_dataset(tmp_path, [], db_row_count=10)
    r = ac050(tmp_path)
    assert r["status"] == "finding"
    assert "geleert" in r["beleg"]


# ---------------------------------------------------------------------------
# AC-074 — cell_id-Eindeutigkeit pro Frame
# ---------------------------------------------------------------------------

def _write_frame(tmp_path, ts, objs):
    d = tmp_path / "objects" / "train_data" / "objects"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{ts}.json").write_text(json.dumps(objs), encoding="utf-8")


def test_ac074_ok_no_frames(tmp_path):
    r = ac074(tmp_path)
    assert r["status"] == "ok"
    assert r["detail"]["frames_checked"] == 0


def test_ac074_ok_unique_cell_ids(tmp_path):
    _write_frame(tmp_path, "2026-08-05_07-40-00", [
        {"cell_id": "1", "is_active_cell": True},
        {"cell_id": "2", "is_active_cell": True},
        {"cell_id": "3", "is_active_cell": False},
    ])
    r = ac074(tmp_path)
    assert r["status"] == "ok"
    assert r["detail"]["frames_checked"] == 1


def test_ac074_finding_duplicate_active_cell_id(tmp_path):
    _write_frame(tmp_path, "2026-08-05_07-45-00", [
        {"cell_id": "9", "is_active_cell": True},
        {"cell_id": "9", "is_active_cell": True},
    ])
    r = ac074(tmp_path)
    assert r["status"] == "finding"
    assert "9" in str(r["detail"]["frames"])


def test_ac074_ignores_non_frame_json(tmp_path):
    # Datei ohne Zeitstempel-Namensmuster darf nicht als Frame gelesen werden.
    d = tmp_path / "objects" / "train_data" / "objects"
    d.mkdir(parents=True, exist_ok=True)
    (d / "latest_objects.json").write_text(
        json.dumps([{"cell_id": "1", "is_active_cell": True},
                    {"cell_id": "1", "is_active_cell": True}]), encoding="utf-8")
    r = ac074(tmp_path)
    assert r["status"] == "ok"
    assert r["detail"]["frames_checked"] == 0


# ---------------------------------------------------------------------------
# AC-079 — ungeschuetzte Zugangsdaten-Kopien
# ---------------------------------------------------------------------------

def test_ac079_ok_only_allowed_env_files(tmp_path):
    (tmp_path / ".env").write_text("A=1", encoding="utf-8")
    (tmp_path / ".env.example").write_text("A=", encoding="utf-8")
    r = ac079(tmp_path)
    assert r["status"] == "ok"


def test_ac079_finding_env_copy(tmp_path):
    (tmp_path / ".env_Copy").write_text("A=1", encoding="utf-8")
    r = ac079(tmp_path)
    assert r["status"] == "finding"
    assert ".env_Copy" in r["detail"]["gefunden"]


def test_ac079_finding_pem_and_key_files(tmp_path):
    (tmp_path / "server.pem").write_bytes(b"x")
    (tmp_path / "id_rsa.key").write_bytes(b"x")
    r = ac079(tmp_path)
    assert r["status"] == "finding"
    assert len(r["detail"]["gefunden"]) == 2


def test_ac079_finding_env_bak_nested(tmp_path):
    d = tmp_path / "backups"
    d.mkdir()
    (d / ".env.bak").write_text("A=1", encoding="utf-8")
    r = ac079(tmp_path)
    assert r["status"] == "finding"
    assert any(".env.bak" in h for h in r["detail"]["gefunden"])
