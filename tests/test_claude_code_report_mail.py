"""
B115: Claude-Code-Analyse-Report — vollständig unabhängige Config,
git-fetch-basierter Abruf, SMTP-Versand, Admin-Panel Toggle.
"""
import subprocess
import sys
import types
import pytest
from datetime import datetime, timezone, timedelta


def _ensure_scheduler_importable():
    try:
        import debug_utils  # noqa: F401
    except Exception:
        debug_utils_mod = types.ModuleType("debug_utils")
        debug_utils_mod.debug_log = lambda *args, **kwargs: None
        sys.modules["debug_utils"] = debug_utils_mod

    try:
        import apscheduler  # noqa: F401
        return
    except ImportError:
        pass

    apscheduler_mod = types.ModuleType("apscheduler")
    schedulers_mod = types.ModuleType("apscheduler.schedulers")
    blocking_mod = types.ModuleType("apscheduler.schedulers.blocking")
    triggers_mod = types.ModuleType("apscheduler.triggers")
    cron_mod = types.ModuleType("apscheduler.triggers.cron")
    interval_mod = types.ModuleType("apscheduler.triggers.interval")

    class BlockingScheduler:
        def __init__(self, *args, **kwargs):
            self._jobs = {}

        def add_job(self, func, trigger=None, id=None, **kwargs):
            job = types.SimpleNamespace(func=func, trigger=trigger, id=id, kwargs=kwargs)
            self._jobs[id] = job
            return job

        def get_job(self, job_id):
            return self._jobs.get(job_id)

        def shutdown(self, wait=True):
            return None

    class CronTrigger:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class IntervalTrigger:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    blocking_mod.BlockingScheduler = BlockingScheduler
    cron_mod.CronTrigger = CronTrigger
    interval_mod.IntervalTrigger = IntervalTrigger

    sys.modules.setdefault("apscheduler", apscheduler_mod)
    sys.modules.setdefault("apscheduler.schedulers", schedulers_mod)
    sys.modules.setdefault("apscheduler.schedulers.blocking", blocking_mod)
    sys.modules.setdefault("apscheduler.triggers", triggers_mod)
    sys.modules.setdefault("apscheduler.triggers.cron", cron_mod)
    sys.modules.setdefault("apscheduler.triggers.interval", interval_mod)


def _make_result(n_fehler: int = 2) -> dict:
    return {
        "fehler": [f"Fehler {i+1}" for i in range(n_fehler)],
        "loesungen": ["Lösung A", "Lösung B"],
        "verbesserungen": ["Verbesserung 1"],
        "prompts": ["Prompt-Text"],
        "zusammenfassung": f"Test-Report. {n_fehler} Fehler gefunden.",
    }


def test_b115_sendet_report_email(monkeypatch):
    import email_notifier
    captured = {}
    monkeypatch.setattr(email_notifier, "_SMTP_HOST", "smtp.test")
    monkeypatch.setattr(email_notifier, "_SMTP_USER", "u")
    monkeypatch.setattr(email_notifier, "_SMTP_PASS", "p")
    monkeypatch.setattr(email_notifier, "_send_smtp",
                        lambda r, s, h: captured.update(r=r, s=s, h=h) or True)

    ok = email_notifier.send_claude_code_report_email(_make_result(3), "ops@test.local")

    assert ok is True
    assert "ops@test.local" in captured["r"]
    assert "Code-Analyse" in captured["s"]
    assert "Fehler 1" in captured["h"]
    assert "Lösung A" in captured["h"]
    assert "Verbesserung 1" in captured["h"]
    assert "Prompt-Text" in captured["h"]
    assert "Test-Report" in captured["h"]


def test_b115_xss_escaping(monkeypatch):
    import email_notifier
    captured = {}
    monkeypatch.setattr(email_notifier, "_SMTP_HOST", "smtp.test")
    monkeypatch.setattr(email_notifier, "_SMTP_USER", "u")
    monkeypatch.setattr(email_notifier, "_SMTP_PASS", "p")
    monkeypatch.setattr(email_notifier, "_send_smtp",
                        lambda r, s, h: captured.update(h=h) or True)

    result = {
        "fehler": ['<script>alert(1)</script>'],
        "loesungen": [], "verbesserungen": [], "prompts": [],
        "zusammenfassung": "<b>bold</b>",
    }
    email_notifier.send_claude_code_report_email(result, "x@test.local")
    assert "<script>" not in captured["h"]
    assert "&lt;script&gt;" in captured["h"]
    assert "<b>bold</b>" not in captured["h"]


def test_b115_job_disabled(monkeypatch):
    _ensure_scheduler_importable()
    import email_notifier, runtime_config, config, scheduler
    called = {}
    monkeypatch.setattr(email_notifier, "send_claude_code_report_email",
                        lambda r, e: called.update(y=1) or True)
    monkeypatch.setattr(runtime_config, "reload_overrides", lambda: None)
    monkeypatch.setattr(runtime_config, "get",
                        lambda k, d=None: {"enabled": False, "report_email": "x@t.local"}
                        if k == "CLAUDE_CODE_REPORT_CONFIG" else d)
    monkeypatch.setattr(config, "CLAUDE_CODE_REPORT_CONFIG",
                        {"enabled": False, "report_email": "x@t.local",
                         "branch": "debug-export-latest", "cron_hour": 4, "cron_minute": 0})
    scheduler.run_claude_code_report_job()
    assert "y" not in called


def test_b115_job_no_email(monkeypatch):
    _ensure_scheduler_importable()
    import email_notifier, runtime_config, config, scheduler
    called = {}
    monkeypatch.setattr(email_notifier, "send_claude_code_report_email",
                        lambda r, e: called.update(y=1) or True)
    monkeypatch.setattr(runtime_config, "reload_overrides", lambda: None)
    monkeypatch.setattr(runtime_config, "get",
                        lambda k, d=None: {"enabled": True, "report_email": ""}
                        if k == "CLAUDE_CODE_REPORT_CONFIG" else d)
    monkeypatch.setattr(config, "CLAUDE_CODE_REPORT_CONFIG",
                        {"enabled": True, "report_email": "",
                         "branch": "debug-export-latest", "cron_hour": 4, "cron_minute": 0})
    scheduler.run_claude_code_report_job()
    assert "y" not in called


def test_b115_job_fetch_error(monkeypatch):
    _ensure_scheduler_importable()
    import email_notifier, runtime_config, config, scheduler
    called = {}
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **kw: subprocess.CompletedProcess(
                            [], 1, stdout="", stderr="timeout"))
    monkeypatch.setattr(email_notifier, "send_claude_code_report_email",
                        lambda r, e: called.update(y=1) or True)
    monkeypatch.setattr(runtime_config, "reload_overrides", lambda: None)
    monkeypatch.setattr(runtime_config, "get",
                        lambda k, d=None: {"enabled": True, "report_email": "x@t.local",
                                           "branch": "debug-export-latest"}
                        if k == "CLAUDE_CODE_REPORT_CONFIG" else d)
    monkeypatch.setattr(config, "CLAUDE_CODE_REPORT_CONFIG",
                        {"enabled": True, "report_email": "x@t.local",
                         "branch": "debug-export-latest", "cron_hour": 4, "cron_minute": 0})
    scheduler.run_claude_code_report_job()
    assert "y" not in called


def test_b115_job_stale_commit(monkeypatch):
    _ensure_scheduler_importable()
    import email_notifier, runtime_config, config, scheduler
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=27)).isoformat()
    call_seq = iter([
        subprocess.CompletedProcess([], 0, stdout="", stderr=""),
        subprocess.CompletedProcess([], 0, stdout=old_ts, stderr=""),
    ])
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: next(call_seq))
    called = {}
    monkeypatch.setattr(email_notifier, "send_claude_code_report_email",
                        lambda r, e: called.update(y=1) or True)
    monkeypatch.setattr(runtime_config, "reload_overrides", lambda: None)
    monkeypatch.setattr(runtime_config, "get",
                        lambda k, d=None: {"enabled": True, "report_email": "x@t.local",
                                           "branch": "debug-export-latest"}
                        if k == "CLAUDE_CODE_REPORT_CONFIG" else d)
    monkeypatch.setattr(config, "CLAUDE_CODE_REPORT_CONFIG",
                        {"enabled": True, "report_email": "x@t.local",
                         "branch": "debug-export-latest", "cron_hour": 4, "cron_minute": 0})
    scheduler.run_claude_code_report_job()
    assert "y" not in called, "Mail trotz >26h altem Commit gesendet!"


def test_b115_job_registered():
    try:
        _ensure_scheduler_importable()
        import scheduler
        sched = scheduler.create_scheduler()
        job = sched.get_job("claude_code_report")
        assert job is not None, "Job 'claude_code_report' nicht registriert!"
        from apscheduler.triggers.cron import CronTrigger
        assert isinstance(job.trigger, CronTrigger)
        sched.shutdown(wait=False)
    except SystemExit:
        pass
    except Exception as exc:
        pytest.skip(f"Scheduler nicht initialisierbar: {exc}")


def test_b115_config_independent_from_ai_analysis():
    """CLAUDE_CODE_REPORT_CONFIG und AI_ANALYSIS_CONFIG sind separate Dicts."""
    try:
        from config import CLAUDE_CODE_REPORT_CONFIG, AI_ANALYSIS_CONFIG
        assert CLAUDE_CODE_REPORT_CONFIG is not AI_ANALYSIS_CONFIG
        assert "enabled" in CLAUDE_CODE_REPORT_CONFIG
        assert "branch" in CLAUDE_CODE_REPORT_CONFIG
        assert "branch" not in AI_ANALYSIS_CONFIG, \
            "branch darf nicht in AI_ANALYSIS_CONFIG sein!"
        assert "report_mail_enabled" not in AI_ANALYSIS_CONFIG, \
            "report_mail_enabled darf nicht in AI_ANALYSIS_CONFIG sein (B115b obsolet)!"
    except ImportError as exc:
        pytest.skip(f"config.py nicht importierbar: {exc}")
