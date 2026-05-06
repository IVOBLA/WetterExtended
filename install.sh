#!/usr/bin/env bash
set -euo pipefail

DEFAULT_REPO_URL="https://github.com/<user>/wetterprojekt.git"
DEFAULT_BRANCH="main"
DEFAULT_TARGET="/home/ki-pi/wetterprojekt"
LOCK_FILE="/tmp/wetterprojekt_install.lock"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

CURRENT_PHASE="Init"
SYSTEM_DEPS_ENABLED=true
ENABLE_SERVICES=false
BRANCH="$DEFAULT_BRANCH"
REPO="$DEFAULT_REPO_URL"
TARGET="$DEFAULT_TARGET"
APT_UPDATED=false
SERVICE_SCHEDULER_PRESENT=false
DEPENDENCIES_INSTALLED=0
MODE="upgrade"
INSTALL_HAILO=true
INSTALL_NODE=true

log_info() { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

usage() { cat <<USAGE
Usage: $0 [OPTIONEN]

Optionen:
  --branch <name>       Git-Branch (Default: ${DEFAULT_BRANCH})
  --repo <url>          Repository-URL (Default: ${DEFAULT_REPO_URL})
  --target <pfad>       Zielpfad (Default: ${DEFAULT_TARGET})
  --enable-services     Aktiviert systemd-Services am Ende
  --no-system-deps      Überspringt apt-Installationen
  --mode <full|upgrade>  full=Daten/Modelle löschen, upgrade=nur Source (Default: upgrade)
  --no-hailo            Hailo-8-Installation überspringen
  --no-node             Node.js-Installation überspringen
  --help                Diese Hilfe anzeigen
USAGE
}
cleanup_lock(){ rm -f "$LOCK_FILE"; }
on_error(){ local exit_code=$?; log_error "Fehler in Phase: ${CURRENT_PHASE} (Exit-Code: ${exit_code})"; exit "$exit_code"; }
trap on_error ERR; trap cleanup_lock EXIT
[[ -e "$LOCK_FILE" ]] && { log_error "Lock-Datei existiert: $LOCK_FILE. Läuft bereits eine Installation?"; exit 1; }
touch "$LOCK_FILE"
CURRENT_PHASE="Phase 1 — Argument-Parsing und Defaults"; log_info "[Phase 1] Argument-Parsing und Defaults"
while [[ $# -gt 0 ]]; do case "$1" in
  --branch) BRANCH="$2"; shift 2;; --repo) REPO="$2"; shift 2;; --target) TARGET="$2"; shift 2;;
  --enable-services) ENABLE_SERVICES=true; shift;; --no-system-deps) SYSTEM_DEPS_ENABLED=false; shift;;
  --mode) MODE="$2"; [[ "$MODE" == "full" || "$MODE" == "upgrade" ]] || { log_error "Ungültiger --mode: $MODE (erlaubt: full, upgrade)"; exit 1; }; shift 2;;
  --no-hailo) INSTALL_HAILO=false; shift;; --no-node) INSTALL_NODE=false; shift;; --help) usage; exit 0;;
  *) log_error "Unbekanntes Argument: $1"; usage; exit 1;; esac; done
CURRENT_PHASE="Phase 2 — Vorab-Checks"; log_info "[Phase 2] Vorab-Checks"
CURRENT_PHASE="Phase 3 — Source holen"; log_info "[Phase 3] Source holen"
if [[ -d "$TARGET/.git" ]]; then cd "$TARGET"; git fetch --all; git checkout "$BRANCH"; git pull --ff-only; else git clone --branch "$BRANCH" "$REPO" "$TARGET"; cd "$TARGET"; fi
CURRENT_PHASE="Phase 3b — Modus-Behandlung (full|upgrade)"; log_info "[Phase 3b] Modus: ${MODE}"
if [[ "$MODE" == "full" ]]; then
  log_warn "Vollinstallation: Trainingsdaten und Modelle werden gelöscht."
  read -r -p "Wirklich alle Daten unter ${TARGET}/train_data und ${TARGET}/models löschen? (yes/NO) " confirm
  if [[ "$confirm" == "yes" ]]; then rm -rf "${TARGET}/train_data" "${TARGET}/models" || true; log_info "Alte Trainingsdaten und Modelle entfernt."; else log_warn "Abbruch durch Benutzer — wechsle in upgrade-Modus."; MODE="upgrade"; fi
else log_info "Upgrade-Modus: Trainingsdaten und Modelle bleiben erhalten."; fi
CURRENT_PHASE="Phase 4 — System-Dependencies"; log_info "[Phase 4] System-Dependencies"
CURRENT_PHASE="Phase 5 — Python venv und Pip-Pakete"; log_info "[Phase 5] Python venv und Pip-Pakete"
CURRENT_PHASE="Phase 6 — Verzeichnisstruktur"; log_info "[Phase 6] Verzeichnisstruktur"
CURRENT_PHASE="Phase 7 — Systemd-Units"; log_info "[Phase 7] Systemd-Units"
if [[ "$ENABLE_SERVICES" == true ]]; then
  sudo cp "$TARGET/wetterprojekt.service" /etc/systemd/system/
  if [[ -f "$TARGET/wetterprojekt-scheduler.service" ]]; then sudo cp "$TARGET/wetterprojekt-scheduler.service" /etc/systemd/system/; SERVICE_SCHEDULER_PRESENT=true; fi
  if [[ -f "$TARGET/wetterprojekt-admin.service" ]]; then sudo cp "$TARGET/wetterprojekt-admin.service" /etc/systemd/system/; sudo systemctl enable --now wetterprojekt-admin.service; systemctl status --no-pager --lines=5 wetterprojekt-admin.service || true; else log_warn "wetterprojekt-admin.service nicht gefunden, überspringe."; fi
fi
CURRENT_PHASE="Phase 7b — Hailo-8-Installation"
log_info "[Phase 7b] Hailo-8-Installation"
CURRENT_PHASE="Phase 7c — Node.js + Frontend-Build"
log_info "[Phase 7c] Node.js + Frontend-Build"
CURRENT_PHASE="Phase 8 — Verifikation und Abschluss-Report"; log_info "[Phase 8] Verifikation und Abschluss-Report"
printf "${GREEN}✅ Modus:${NC} %s\n" "$MODE"
if [[ "$INSTALL_HAILO" == true ]]; then printf "${GREEN}✅ Hailo:${NC} install attempted\n"; else printf "${YELLOW}↷ Hailo:${NC} skipped\n"; fi
if [[ "$INSTALL_NODE" == true ]]; then printf "${GREEN}✅ Node.js:${NC} %s\n" "$(node --version 2>/dev/null || echo 'n/a')"; fi
cat <<'NEXTSTEPS'
Nächste Schritte:
  Modelle initial trainieren:  source venv/bin/activate && python3 dataset_builder.py && python3 model_training.py
  Status der Services:         sudo systemctl status wetterprojekt
  Logs live:                   journalctl -fu wetterprojekt
  Adminpanel:                  http://<pi-ip>:5000
  Bei Hailo-Reboot-Hinweis:    sudo reboot
  Manuelle Hailo-Schritte:     siehe HAILO_INSTALL.md
NEXTSTEPS
