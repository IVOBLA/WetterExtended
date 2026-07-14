"""B357: Strukturierte ConvLSTM-Trainings-Telemetrie (Kind-Prozess +
Eltern-Fallback bei SIGKILL/Timeout) und deren Einbindung in den 24h-Export.
Statische Quelltext-Checks + ein isolierter Logiktest fuer den JSONL-Writer
(kein TF/psutil-Laufzeitimport noetig fuer die reinen Struktur-Assertions)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_train_convlstm_returns_batch_size_used():
    src = _read("radar_convlstm.py")
    fn = src.split("def train_convlstm(")[1].split("\ndef ")[0]
    assert '"batch_size_used": _bs' in fn


def test_cli_writes_telemetry_on_all_paths():
    src = _read("radar_convlstm.py")
    assert "_write_training_run_record" in src
    cli = src.split("def _cli():")[1]
    assert "outcome" in cli
    assert "except Exception as exc:" in cli


def test_scheduler_has_fallback_record_writer():
    src = _read("scheduler.py")
    assert "_write_convlstm_fallback_record" in src
    job = src.split("def run_convlstm_weekly_job(")[1].split("\ndef ")[0]
    # B363: B360 ersetzte die feste Zeile outcome="system_oom_kill" durch eine
    # Fallunterscheidung (deckt zusaetzlich child_aborted_signal_N fuer
    # SIGABRT/std::bad_alloc und sonstige Signal-Tode ab). Der String
    # "system_oom_kill" bleibt als Literal im Code vorhanden (Zuweisung an
    # die outcome-Variable), nur nicht mehr als direktes Keyword-Argument.
    assert '"system_oom_kill"' in job
    assert "child_aborted_signal_" in job
    assert "outcome=outcome" in job
    assert 'outcome="timeout"' in job


def test_diagnose_script_exists_and_has_main():
    assert os.path.exists("tools/diagnose_convlstm_training.py")
    src = _read("tools/diagnose_convlstm_training.py")
    assert "convlstm_training_runs.jsonl" in src
    assert "def main(" in src


def test_export_diagnosis_wires_convlstm_training():
    src = _read("export_diagnosis.py")
    assert "run_convlstm_training_diagnosis_before_export" in src
    assert "load_latest_convlstm_training_diagnosis" in src


def test_debug_export_includes_convlstm_training_diagnosis():
    src = _read("debug_export.py")
    assert "run_convlstm_training_diagnosis_before_export" in src
    assert '"convlstm_training_diagnosis": convlstm_training_diagnosis,' in src
    assert '"convlstm_training_diagnosis_latest.json",' in src
    assert '"convlstm_training_runs.jsonl",' in src


def test_write_training_run_record_writes_valid_jsonl(tmp_path, monkeypatch):
    import radar_convlstm as rc
    import config
    ev_dir = tmp_path / "evaluation"
    monkeypatch.setattr(config, "SAVE_PATHS", {"evaluation": str(ev_dir)}, raising=False)
    rc._write_training_run_record({"outcome": "success", "batch_size_used": 2})
    out_file = ev_dir / "convlstm_training_runs.jsonl"
    assert out_file.exists()
    line = out_file.read_text(encoding="utf-8").strip().splitlines()[-1]
    row = json.loads(line)
    assert row["outcome"] == "success"
    assert row["source"] == "child"
    assert "timestamp_utc" in row
