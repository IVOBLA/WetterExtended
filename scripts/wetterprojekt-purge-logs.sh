#!/usr/bin/env bash
set -euo pipefail

systemctl stop wetterprojekt wetterprojekt-scheduler wetterprojekt-admin || true
journalctl --rotate || true
journalctl --vacuum-time=1s || true
systemctl restart systemd-journald || true
systemctl start wetterprojekt wetterprojekt-scheduler wetterprojekt-admin || true
