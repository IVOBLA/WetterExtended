"""P114 — Welle C (Teil 1): zwei ACs deterministisch migriert (AC-073, AC-045).

AC-018, AC-033 und AC-044 sind bewusst NICHT Teil dieser Welle — die dafür
nötigen Daten sind entweder nicht persistiert (AC-018: model_rejection_reason
existiert nur im nicht geschriebenen admin_diagnostics-Zweig) oder erfordern
eine Zeitreihe mehrerer Snapshots bzw. eine Log/JSONL-Zeitkorrelation, die noch
nicht ausreichend verifiziert ist (AC-033, AC-044).
"""
import json
from pathlib import Path

from tools.ai_checks.checks_local import (
    check_ac073_lineage_state_corruption as ac073,
    check_ac045_rejected_training_versions as ac045,
)


# ---------------------------------------------------------------------------
# AC-073
# ---------------------------------------------------------------------------

def test_ac073_ok_clean_export(tmp_path):
    d = tmp_path / "api_logs" / "journal"
    d.mkdir(parents=True)
    (d / "wetterprojekt.service.log").write_text("normaler Betrieb, keine Fehler\n", encoding="utf-8")
    r = ac073(tmp_path)
    assert r["status"] == "ok"


def test_ac073_ok_no_export_content_at_all(tmp_path):
    r = ac073(tmp_path)
    assert r["status"] == "ok"


def test_ac073_finding_load_error_in_log(tmp_path):
    d = tmp_path / "api_logs" / "journal"
    d.mkdir(parents=True)
    (d / "wetterprojekt-admin.service.log").write_text(
        "Aug 05 07:00:00 host wetterprojekt-admin[1]: "
        "[CELL-LINEAGE] State konnte nicht geladen werden (train_data/cell_lineage/cell_lineage_state.json): boom\n",
        encoding="utf-8")
    r = ac073(tmp_path)
    assert r["status"] == "finding"
    assert r["detail"]["log_hits"]


def test_ac073_finding_save_error_in_other_service_log(tmp_path):
    d = tmp_path / "api_logs" / "journal"
    d.mkdir(parents=True)
    (d / "wetterprojekt.service.log").write_text(
        "[CELL-LINEAGE] State konnte nicht gespeichert werden (x): boom\n", encoding="utf-8")
    r = ac073(tmp_path)
    assert r["status"] == "finding"


def test_ac073_finding_quarantined_corrupt_file(tmp_path):
    d = tmp_path / "cell_lineage" / "train_data" / "cell_lineage"
    d.mkdir(parents=True)
    (d / "cell_lineage_state.json.corrupt.20260805071500").write_bytes(b"defekt")
    r = ac073(tmp_path)
    assert r["status"] == "finding"
    assert r["detail"]["corrupt_files"]


def test_ac073_finding_stray_tmp_file(tmp_path):
    d = tmp_path / "cell_lineage" / "train_data" / "cell_lineage"
    d.mkdir(parents=True)
    (d / "cell_lineage_state.json.4242.deadbeef.tmp").write_bytes(b"halb geschrieben")
    r = ac073(tmp_path)
    assert r["status"] == "finding"
    assert r["detail"]["stray_tmp"]


def test_ac073_ignores_unrelated_tmp_files(tmp_path):
    # .tmp-Dateien AUSSERHALB von cell_lineage duerfen nicht faelschlich zaehlen.
    d = tmp_path / "hydro_ml"
    d.mkdir(parents=True)
    (d / "something.tmp").write_bytes(b"unrelated")
    r = ac073(tmp_path)
    assert r["status"] == "ok"


# ---------------------------------------------------------------------------
# AC-045
# ---------------------------------------------------------------------------

def _write_snapshot(tmp_path, active_version, versions):
    d = tmp_path / "diagnostics"
    d.mkdir(parents=True, exist_ok=True)
    doc = {"progress": {"active_version": active_version, "versions": versions}}
    (d / "progress_snapshot.json").write_text(json.dumps(doc), encoding="utf-8")


def test_ac045_ok_no_snapshot(tmp_path):
    r = ac045(tmp_path)
    assert r["status"] == "ok"


def test_ac045_ok_active_is_promoted(tmp_path):
    _write_snapshot(tmp_path, "v_20260805_0700", [
        {"version_id": "v_20260805_0700", "status": "promoted", "is_active": True},
        {"version_id": "v_20260804_0700", "status": "rejected", "is_active": False},
    ])
    r = ac045(tmp_path)
    assert r["status"] == "ok"


def test_ac045_finding_active_is_rejected(tmp_path):
    _write_snapshot(tmp_path, "v_20260805_0700", [
        {"version_id": "v_20260805_0700", "status": "rejected", "is_active": True},
    ])
    r = ac045(tmp_path)
    assert r["status"] == "finding"
    assert "v_20260805_0700" in r["beleg"]


def test_ac045_context_counts_rejected_log_lines(tmp_path):
    _write_snapshot(tmp_path, "v_1", [{"version_id": "v_1", "status": "promoted", "is_active": True}])
    d = tmp_path / "api_logs" / "journal"
    d.mkdir(parents=True)
    (d / "wetterprojekt-scheduler.service.log").write_text(
        "[TRAINING] REJECTED 2026-08-04_07-00-00 (inkompatibel): reason\n"
        "[TRAINING] REJECTED 2026-08-05_07-00-00: reason\n", encoding="utf-8")
    r = ac045(tmp_path)
    assert r["status"] == "ok"
    assert r["detail"]["rejected_log_lines"] == 2
