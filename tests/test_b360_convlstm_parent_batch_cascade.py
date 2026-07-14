"""B360: Eltern-seitige Batch-Size-Kaskade in scheduler.run_convlstm_weekly_job,
da native C++-Allocator-Aborts (std::bad_alloc -> SIGABRT, rc=-6) fuer Python
nicht abfangbar sind und die kindseitige Kaskade (B356) daher nie erreichen.
Statische Quelltext-Checks + ein Logiktest fuer die erweiterte Fallback-
Telemetrie."""
import json
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_scheduler_has_parent_batch_size_cascade():
    src = _read("scheduler.py")
    job = src.split("def run_convlstm_weekly_job(")[1].split("\ndef ")[0]
    assert "_batch_size_cascade = (4, 2, 1)" in job
    assert '"--batch-size"' in job
    assert "proc.returncode < 0" in job, "Signalbasierter Tod (rc<0) wird nicht erkannt"


def test_scheduler_handles_generic_signal_deaths_not_only_sigkill():
    src = _read("scheduler.py")
    job = src.split("def run_convlstm_weekly_job(")[1].split("\ndef ")[0]
    assert "child_aborted_signal_" in job
    assert "system_oom_kill" in job


def test_fallback_record_accepts_batch_size_and_attempt():
    src = _read("scheduler.py")
    fn = src.split("def _write_convlstm_fallback_record(")[1].split("\ndef ")[0]
    assert "batch_size" in fn
    assert "attempt" in fn
    assert '"batch_size_used": batch_size' in fn
    assert '"batch_size_cascade_attempts": attempt' in fn


def test_fallback_record_writes_batch_size_and_attempt(tmp_path, monkeypatch):
    class _Trigger:
        def __init__(self, *args, **kwargs):
            pass

    monkeypatch.setitem(sys.modules, "apscheduler", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "apscheduler.schedulers", types.SimpleNamespace())
    monkeypatch.setitem(
        sys.modules,
        "apscheduler.schedulers.blocking",
        types.SimpleNamespace(BlockingScheduler=object),
    )
    monkeypatch.setitem(sys.modules, "apscheduler.triggers", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "apscheduler.triggers.cron", types.SimpleNamespace(CronTrigger=_Trigger))
    monkeypatch.setitem(sys.modules, "apscheduler.triggers.interval", types.SimpleNamespace(IntervalTrigger=_Trigger))

    import config
    monkeypatch.setattr(config, "SAVE_PATHS", {"evaluation": str(tmp_path)}, raising=False)
    import scheduler as sched
    sched._write_convlstm_fallback_record(
        outcome="child_aborted_signal_6", effective_mem_gb=4.88,
        static_mem_gb=12, batch_size=4, attempt=1,
    )
    path = tmp_path / "convlstm_training_runs.jsonl"
    assert path.exists()
    row = json.loads(path.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert row["outcome"] == "child_aborted_signal_6"
    assert row["batch_size_used"] == 4
    assert row["batch_size_cascade_attempts"] == 1


def test_diagnose_script_explains_signal_abort_outcome():
    src = _read("tools/diagnose_convlstm_training.py")
    assert "child_aborted_signal_" in src
    assert "std::bad_alloc" in src


def test_training_jsx_handles_signal_abort_outcome():
    src = _read("frontend/src/pages/Training.jsx")
    assert "child_aborted_signal_" in src
    assert "isSignalAbort" in src
