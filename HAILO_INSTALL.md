# Hailo-8 Installation auf Raspberry Pi 5

## Voraussetzungen
- Raspberry Pi 5 mit Hailo-8-Modul (z.B. Raspberry Pi AI Kit)
- Pi-OS Bookworm 64-bit
- Aktueller Kernel (>= 6.6) mit PCIe-Support

## Admin-Loglöschung und KI-Logschutz

Bei einer Vollinstallation auf Raspberry Pi 5/Hailo muss der Installer auch die sichere Loglöschung konfigurieren.

Anforderungen:
- Der Admin-Button "Logs löschen" setzt immer einen Clear-Marker in `train_data/evaluation/log_clear_state.json`.
- Logs vor `cleared_at_utc` dürfen weder in der Admin-Oberfläche angezeigt noch an KI-/LLM-/Analysefunktionen übergeben werden.
- API-/Evaluation-JSONL-Logs werden physisch gelöscht.
- Systemd-Journal-Einträge bleiben standardmäßig im Betriebssystem erhalten, werden aber ab `cleared_at_utc` ausgeblendet.
- Optional kann physisches Journal-Löschen aktiviert werden: `ALLOW_SYSTEM_LOG_PURGE=true`.
- Dafür installiert `install.sh` ein Root-Script: `/usr/local/bin/wetterprojekt-purge-logs.sh`.
- Passwortloses sudo darf nur für dieses eine Script erlaubt werden: `/etc/sudoers.d/wetterprojekt-logs`.
- Kein pauschales `NOPASSWD: ALL`.
- Kein direkter `sudo journalctl`-Aufruf aus Flask.
- Das Script darf nur folgende Aktionen ausführen:
  - `systemctl stop/start wetterprojekt, wetterprojekt-scheduler, wetterprojekt-admin`
  - `journalctl --rotate`
  - `journalctl --vacuum-time=1s`
  - `systemctl restart systemd-journald`
