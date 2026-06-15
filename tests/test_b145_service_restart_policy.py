"""B145: systemd-Services sind self-healing — kein dauerhaftes 'failed' nach Crashes.

Statischer Check der drei Unit-Files: StartLimitIntervalSec=0, kein StartLimitBurst,
Restart-Policy gesetzt. (Läuft relativ zum Projektstamm, wie die übrigen Tests.)"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SERVICES = [
    "wetterprojekt.service",
    "wetterprojekt-scheduler.service",
    "wetterprojekt-admin.service",
]


def _read(name):
    with open(name, encoding="utf-8") as f:
        return f.read()


def test_services_exist():
    for s in SERVICES:
        assert os.path.exists(s), f"{s} fehlt"


def test_start_limit_interval_zero():
    for s in SERVICES:
        m = re.search(r"StartLimitIntervalSec\s*=\s*(\d+)", _read(s))
        assert m, f"{s}: StartLimitIntervalSec fehlt"
        assert int(m.group(1)) == 0, f"{s}: StartLimitIntervalSec != 0 (Self-Healing fehlt)"


def test_no_start_limit_burst():
    for s in SERVICES:
        assert "StartLimitBurst" not in _read(s), f"{s}: StartLimitBurst noch vorhanden"


def test_restart_policy_present():
    for s in SERVICES:
        assert re.search(r"Restart\s*=\s*(on-failure|always)", _read(s)), \
            f"{s}: keine Restart-Policy gesetzt"
