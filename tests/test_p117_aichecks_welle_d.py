"""P117 — Welle D: drei ACs deterministisch migriert (AC-010, AC-058, AC-075)."""
import json
import sqlite3

from tools.ai_checks.checks_local import (
    check_ac010_nested_archives_in_export as ac010,
    check_ac058_hydro_flood_risk_store_defect as ac058,
    check_ac075_hydro_ml_pytest_contamination as ac075,
)


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_ac010_ok_no_zips(tmp_path):
    assert ac010(tmp_path)["status"] == "ok"


def test_ac010_finding_recursive_under_latest_export(tmp_path):
    d = tmp_path / "evaluation" / "latest_export"
    d.mkdir(parents=True)
    (d / "part1.zip").write_bytes(b"PK")
    r = ac010(tmp_path)
    assert r["status"] == "finding"
    assert "Rekursion" in r["beleg"]


def test_ac010_finding_legitimate_zip_outside_latest_export(tmp_path):
    d = tmp_path / "external_responses"
    d.mkdir(parents=True)
    (d / "archive.zip").write_bytes(b"PK")
    r = ac010(tmp_path)
    assert r["status"] == "finding"
    assert "Rekursion" not in r["beleg"]
    assert "legitime Nutzdaten" in r["beleg"]


def test_ac058_ok_clean_export(tmp_path):
    _write(tmp_path / "api_logs/nginx/nginx_access.log",
           '1.2.3.4 - - [07/Aug/2026:05:42:53 +0200] "GET /api/hydro/flood-risk HTTP/1.1" 200 15230 "-" "UA"\n')
    _write(tmp_path / "train_data/evaluation/api_health.jsonl", "")
    _write(tmp_path / "train_data/hydro/impact/latest_hydro_flood_risk.json",
           json.dumps({"sample_store_status": "ok"}))
    assert ac058(tmp_path)["status"] == "ok"


def test_ac058_finding_small_nginx_responses_exact_105(tmp_path):
    lines = "\n".join(f'1.2.3.4 - - [07/Aug/2026:05:{i:02d}:00 +0200] "GET /api/hydro/flood-risk HTTP/1.1" 200 105 "-" "UA"' for i in range(3))
    _write(tmp_path / "api_logs/nginx/nginx_access.log", lines)
    r = ac058(tmp_path)
    assert r["status"] == "finding"
    assert "105 Bytes" in r["beleg"]
    assert "disk image is malformed" in r["beleg"]


def test_ac058_ignores_large_and_unrelated_responses(tmp_path):
    lines = "\n".join([
        '1.2.3.4 - - [07/Aug/2026:05:00:00 +0200] "GET /api/hydro/flood-risk HTTP/1.1" 200 15000 "-" "UA"',
        '1.2.3.4 - - [07/Aug/2026:05:01:00 +0200] "GET /api/forecast HTTP/1.1" 200 50 "-" "UA"'])
    _write(tmp_path / "api_logs/nginx/nginx_access.log", lines)
    assert ac058(tmp_path)["status"] == "ok"


def test_ac058_finding_frequent_hydro_api_failures(tmp_path):
    recs = [json.dumps({"ts_utc": f"2026-08-06T0{i}:00:00Z", "service": "hydro_api", "reason": "Timeout"}) for i in range(7)]
    _write(tmp_path / "train_data/evaluation/api_health.jsonl", "\n".join(recs))
    r = ac058(tmp_path)
    assert r["status"] == "finding"
    assert "7 hydro_api-Fehler" in r["beleg"]


def test_ac058_ignores_other_services_in_api_health(tmp_path):
    recs = [json.dumps({"ts_utc": "2026-08-06T00:00:00Z", "service": "GeoSphere-TAWES", "reason": "Timeout"}) for _ in range(10)]
    _write(tmp_path / "train_data/evaluation/api_health.jsonl", "\n".join(recs))
    assert ac058(tmp_path)["status"] == "ok"


def test_ac058_finding_corrupt_sqlite_snapshot(tmp_path):
    d = tmp_path / "hydro_ml"
    d.mkdir()
    (d / "hydro_flood_samples_snapshot.sqlite3").write_bytes(b"kein sqlite header")
    r = ac058(tmp_path)
    assert r["status"] == "finding"
    assert "integrity_check" in r["beleg"]


def test_ac058_ok_valid_sqlite_snapshot(tmp_path):
    d = tmp_path / "hydro_ml"
    d.mkdir()
    con = sqlite3.connect(str(d / "hydro_flood_samples_snapshot.sqlite3"))
    con.execute("CREATE TABLE t(x)")
    con.commit()
    con.close()
    assert ac058(tmp_path)["status"] == "ok"


def test_ac058_finding_missing_risk_cache_despite_scanned_root(tmp_path):
    _write(tmp_path / "manifest.json", json.dumps({"scanned_roots": ["/home/ki-pi/wetterprojekt/train_data/hydro/impact"]}))
    r = ac058(tmp_path)
    assert r["status"] == "finding"
    assert "nie geschrieben" in r["beleg"]


def test_ac058_ok_missing_risk_cache_when_root_not_scanned(tmp_path):
    _write(tmp_path / "manifest.json", json.dumps({"scanned_roots": []}))
    assert ac058(tmp_path)["status"] == "ok"


def test_ac058_finding_degraded_sample_store(tmp_path):
    _write(tmp_path / "train_data/hydro/impact/latest_hydro_flood_risk.json",
           json.dumps({"sample_store_status": "degraded", "sample_store_faults": [{"stage": "write"}, {"stage": "read"}]}))
    r = ac058(tmp_path)
    assert r["status"] == "finding"
    assert "degraded" in r["beleg"]
    assert r["detail"]["sample_store_faults"] == ["write", "read"]


def test_ac075_ok_clean_paths_and_sizes(tmp_path):
    _write(tmp_path / "hydro_ml/hydro_sample_db_integrity.json", json.dumps({"db_path": "/home/ki-pi/wetterprojekt/train_data/hydro/ml/hydro_flood_samples.sqlite3"}))
    _write(tmp_path / "hydro_ml/hydro_ml_maintenance_latest.json", json.dumps({"db_size_before": 5_000_000, "db_size_after": 4_800_000}))
    assert ac075(tmp_path)["status"] == "ok"


def test_ac075_finding_pytest_db_path(tmp_path):
    _write(tmp_path / "hydro_ml/hydro_sample_db_integrity.json", json.dumps({"db_path": "/tmp/pytest-of-ki-pi/pytest-49/test_x/hydro.sqlite3"}))
    r = ac075(tmp_path)
    assert r["status"] == "finding"
    assert "B455" in r["beleg"]


def test_ac075_finding_implausibly_small_db_size(tmp_path):
    _write(tmp_path / "hydro_ml/hydro_ml_maintenance_latest.json", json.dumps({"db_size_before": 80_000, "db_size_after": 79_000}))
    r = ac075(tmp_path)
    assert r["status"] == "finding"
    assert "db_size_before" in r["beleg"]
    assert "db_size_after" in r["beleg"]


def test_ac075_ok_no_files_present(tmp_path):
    assert ac075(tmp_path)["status"] == "ok"
