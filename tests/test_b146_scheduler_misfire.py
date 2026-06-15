"""B146: Scheduler setzt job_defaults mit misfire_grace_time (verpasste Jobs nachholen).

Statischer Quelltext-Check (kein Import von scheduler.py — vermeidet schwere TF-Importe)."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_config_has_misfire_grace():
    cfg = _read("config.py")
    m = re.search(r"SCHEDULER_MISFIRE_GRACE_S\s*:\s*int\s*=\s*(\d+)", cfg)
    assert m, "SCHEDULER_MISFIRE_GRACE_S fehlt in config.py"
    assert int(m.group(1)) >= 600, "Kulanzfenster sollte >= 600 s sein"


def test_scheduler_sets_job_defaults():
    src = _read("scheduler.py")
    assert "job_defaults" in src, "BlockingScheduler ohne job_defaults"
    assert "misfire_grace_time" in src, "misfire_grace_time nicht gesetzt"
    assert "SCHEDULER_MISFIRE_GRACE_S" in src, "Konfig-Wert nicht referenziert"


def test_blockingscheduler_still_has_timezone():
    src = _read("scheduler.py")
    assert 'timezone="Europe/Vienna"' in src
