#!/usr/bin/env bash
# /usr/local/bin/wetterprojekt-purge-logs.sh
#
# Wird von Flask (app.py) via sudoers aufgerufen:
#   sudo /usr/local/bin/wetterprojekt-purge-logs.sh
#
# Erlaubte Aktionen laut /etc/sudoers.d/wetterprojekt-logs:
#   systemctl stop/start wetterprojekt, wetterprojekt-scheduler, wetterprojekt-admin
#   journalctl --rotate
#   journalctl --vacuum-time=1s
#   systemctl restart systemd-journald
#
# WICHTIG: Dieses Script wird vom wetterprojekt-admin-Service aufgerufen und
# stoppt diesen Service selbst. Durch KillMode=control-group (systemd-Standard)
# werden beim Stop alle Prozesse im cgroup-Container terminiert — einschließlich
# dieses Scripts. Daher wird der Neustart via systemd-run ZUERST geplant,
# bevor irgendein Service gestoppt wird.

set -euo pipefail

# ── Schritt 1: Neustart als unabhängige transiente systemd-Unit vorab einplanen ──
# systemd-run erstellt eine neue transiente Unit außerhalb des wetterprojekt-admin-
# cgroups. Diese Unit überlebt das Stoppen des Flask-Services und startet die
# Services nach 5 Sekunden (Wartezeit für Journal-Vacuum) neu.
systemd-run --no-block sh -c \
  'sleep 5; systemctl start wetterprojekt wetterprojekt-scheduler wetterprojekt-admin' \
  2>/dev/null || true

# ── Schritt 2: Services stoppen ──
systemctl stop wetterprojekt wetterprojekt-scheduler wetterprojekt-admin || true

# ── Schritt 3: Journal rotieren und bereinigen ──
journalctl --rotate || true
journalctl --vacuum-time=1s || true

# ── Schritt 4: systemd-journald neu starten ──
systemctl restart systemd-journald || true

# Schritt 5 (Service-Neustart) läuft bereits via systemd-run aus Schritt 1.
# Kein manueller start-Aufruf nötig.
