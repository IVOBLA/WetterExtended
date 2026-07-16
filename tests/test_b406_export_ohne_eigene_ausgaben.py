"""B406: Der Export darf keine eigenen Ausgaben enthalten und muss die Diagnose melden."""
from pathlib import Path

import pytest

import debug_export


def test_zip_files_are_excluded():
    """KERNREGRESSION: Ein Debug-Archiv darf kein anderes Archiv enthalten."""
    p = Path("train_data/evaluation/latest_export/wetterextended_debug2.zip")
    assert debug_export._is_excluded_from_export(p)


def test_latest_export_dir_is_excluded():
    """Der Ablageort der eigenen ZIPs ist tabu — auch fuer Nicht-ZIP-Dateien."""
    p = Path("train_data/evaluation/latest_export/latest_export_meta.json")
    assert debug_export._is_excluded_from_export(p)


def test_normal_files_are_not_excluded():
    for p in (Path("train_data/association/2026-07-16_04-55-00.json"),
              Path("train_data/cell_lineage/cell_lineage_events.jsonl"),
              Path("train_data/evaluation/forecast_error_details.jsonl")):
        assert not debug_export._is_excluded_from_export(p), f"{p} faelschlich ausgeschlossen"


def test_iter_files_skips_own_exports(tmp_path):
    ev = tmp_path / "train_data" / "evaluation"
    (ev / "latest_export").mkdir(parents=True)
    (ev / "latest_export" / "wetterextended_debug2.zip").write_bytes(b"PK\x03\x04alt")
    (ev / "forecast_error_details.jsonl").write_text('{"a":1}\n', encoding="utf-8")
    files = [p.name for p in debug_export._iter_files(ev)]
    assert "forecast_error_details.jsonl" in files
    assert "wetterextended_debug2.zip" not in files, "Eigener Export wurde erneut verpackt"


def test_iter_files_on_single_zip_yields_nothing(tmp_path):
    z = tmp_path / "wetterextended_debug1.zip"
    z.write_bytes(b"PK\x03\x04")
    assert list(debug_export._iter_files(z)) == []


def test_diagnosis_report_detects_missing(tmp_path):
    r = debug_export._diagnosis_presence_report(tmp_path)
    assert r["association"]["status"] == "missing"
    assert "resolved" in r["association"]


def test_diagnosis_report_detects_empty(tmp_path):
    (tmp_path / "train_data" / "association").mkdir(parents=True)
    r = debug_export._diagnosis_presence_report(tmp_path)
    assert r["association"]["status"] == "empty"


def test_diagnosis_report_detects_ok(tmp_path):
    d = tmp_path / "train_data" / "association"
    d.mkdir(parents=True)
    (d / "2026-07-16_04-55-00.json").write_text("{}", encoding="utf-8")
    r = debug_export._diagnosis_presence_report(tmp_path)
    assert r["association"]["status"] == "ok"
    assert r["association"]["files"] == 1
    assert "newest_mtime_utc" in r["association"]


def test_association_still_in_export_list():
    import inspect
    src = inspect.getsource(debug_export)
    assert 'Path("train_data/association")' in src


def test_aichecks_file_exists():
    """B406: AIChecks.md ist ab sofort verbindlich."""
    p = Path("AIChecks.md")
    assert p.exists(), "AIChecks.md fehlt im Project Root"
    txt = p.read_text(encoding="utf-8")
    assert "AC-001" in txt
    assert "## Offen" in txt
