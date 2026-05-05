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

log_info() { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

usage() {
  cat <<USAGE
Usage: $0 [OPTIONEN]

Optionen:
  --branch <name>       Git-Branch (Default: ${DEFAULT_BRANCH})
  --repo <url>          Repository-URL (Default: ${DEFAULT_REPO_URL})
  --target <pfad>       Zielpfad (Default: ${DEFAULT_TARGET})
  --enable-services     Aktiviert systemd-Services am Ende
  --no-system-deps      Überspringt apt-Installationen
  --help                Diese Hilfe anzeigen
USAGE
}

cleanup_lock() {
  rm -f "$LOCK_FILE"
}

on_error() {
  local exit_code=$?
  log_error "Fehler in Phase: ${CURRENT_PHASE} (Exit-Code: ${exit_code})"
  exit "$exit_code"
}

trap on_error ERR
trap cleanup_lock EXIT

if [[ -e "$LOCK_FILE" ]]; then
  log_error "Lock-Datei existiert: $LOCK_FILE. Läuft bereits eine Installation?"
  exit 1
fi

touch "$LOCK_FILE"

CURRENT_PHASE="Phase 1 — Argument-Parsing und Defaults"
log_info "[Phase 1] Argument-Parsing und Defaults"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --branch)
      [[ $# -ge 2 ]] || { log_error "Fehlender Wert für --branch"; usage; exit 1; }
      BRANCH="$2"
      shift 2
      ;;
    --repo)
      [[ $# -ge 2 ]] || { log_error "Fehlender Wert für --repo"; usage; exit 1; }
      REPO="$2"
      shift 2
      ;;
    --target)
      [[ $# -ge 2 ]] || { log_error "Fehlender Wert für --target"; usage; exit 1; }
      TARGET="$2"
      shift 2
      ;;
    --enable-services)
      ENABLE_SERVICES=true
      shift
      ;;
    --no-system-deps)
      SYSTEM_DEPS_ENABLED=false
      shift
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      log_error "Unbekanntes Argument: $1"
      usage
      exit 1
      ;;
  esac
done

CURRENT_PHASE="Phase 2 — Vorab-Checks"
log_info "[Phase 2] Vorab-Checks"

if (( BASH_VERSINFO[0] < 4 )); then
  log_error "Bash >= 4 erforderlich. Gefunden: ${BASH_VERSION}"
  exit 1
fi

if [[ "${EUID}" -eq 0 ]]; then
  log_error "Bitte als normaler User ausführen, sudo wird intern verwendet."
  exit 1
fi

if [[ "$PWD" == "$TARGET"* ]]; then
  log_warn "Hinweis: du updates dich gerade selbst — Bash übernimmt die neue Version erst beim nächsten Start."
fi

ensure_command() {
  local cmd="$1"
  local pkg="$2"
  if command -v "$cmd" >/dev/null 2>&1; then
    return 0
  fi

  if [[ "$SYSTEM_DEPS_ENABLED" == false ]]; then
    log_error "Benötigter Befehl fehlt: $cmd (Paket: $pkg). Ohne --no-system-deps nicht installierbar."
    exit 1
  fi

  if [[ "$APT_UPDATED" == false ]]; then
    sudo apt update
    APT_UPDATED=true
  fi

  if sudo apt install -y "$pkg"; then
    DEPENDENCIES_INSTALLED=$((DEPENDENCIES_INSTALLED + 1))
  else
    log_warn "Konnte Paket nicht installieren: $pkg (für $cmd)."
  fi

  if ! command -v "$cmd" >/dev/null 2>&1; then
    log_error "Befehl weiterhin nicht verfügbar: $cmd"
    exit 1
  fi
}

ensure_command git git
ensure_command python3 python3
ensure_command sudo sudo

if [[ "$SYSTEM_DEPS_ENABLED" == true ]]; then
  if ! dpkg -s python3-venv >/dev/null 2>&1; then
    if [[ "$APT_UPDATED" == false ]]; then
      sudo apt update
      APT_UPDATED=true
    fi
    if sudo apt install -y python3-venv; then
      DEPENDENCIES_INSTALLED=$((DEPENDENCIES_INSTALLED + 1))
    else
      log_warn "Konnte Paket python3-venv nicht installieren."
    fi
  fi
else
  python3 -m venv --help >/dev/null 2>&1 || {
    log_error "python3-venv fehlt und --no-system-deps wurde gesetzt."
    exit 1
  }
fi

CURRENT_PHASE="Phase 3 — Source holen"
log_info "[Phase 3] Source holen"

if [[ -d "$TARGET/.git" ]]; then
  cd "$TARGET"
  git fetch --all
  git checkout "$BRANCH"
  if ! git pull --ff-only; then
    log_error "git pull --ff-only fehlgeschlagen (z. B. lokale Änderungen). Bitte manuell prüfen."
    exit 1
  fi
else
  git clone --branch "$BRANCH" "$REPO" "$TARGET"
  cd "$TARGET"
fi

CURRENT_PHASE="Phase 4 — System-Dependencies"
log_info "[Phase 4] System-Dependencies"

if [[ "$SYSTEM_DEPS_ENABLED" == true ]]; then
  if [[ "$APT_UPDATED" == false ]]; then
    sudo apt update
    APT_UPDATED=true
  fi

  apt_packages=(
    python3-pip python3-venv unzip git
    libatlas-base-dev libopenjp2-7 libtiff-dev libjpeg-dev libfreetype6-dev
    libgeos-dev libgdal-dev libhdf5-dev
  )

  for pkg in "${apt_packages[@]}"; do
    if sudo apt install -y "$pkg"; then
      DEPENDENCIES_INSTALLED=$((DEPENDENCIES_INSTALLED + 1))
    else
      log_warn "Paket nicht verfügbar/fehlgeschlagen: $pkg — fahre fort."
    fi
  done
else
  log_warn "System-Dependencies übersprungen (--no-system-deps)."
fi

CURRENT_PHASE="Phase 5 — Python venv und Pip-Pakete"
log_info "[Phase 5] Python venv und Pip-Pakete"

if [[ ! -d "$TARGET/venv" ]]; then
  python3 -m venv "$TARGET/venv"
fi

# shellcheck disable=SC1091
source "$TARGET/venv/bin/activate"

pip install --upgrade pip wheel setuptools
if ! pip install -r "$TARGET/requirements.txt"; then
  log_error "pip install -r requirements.txt fehlgeschlagen."
  exit 1
fi

CURRENT_PHASE="Phase 6 — Verzeichnisstruktur"
log_info "[Phase 6] Verzeichnisstruktur"

mkdir -p \
  "$TARGET/train_data/radar" \
  "$TARGET/train_data/objects" \
  "$TARGET/train_data/weather" \
  "$TARGET/train_data/wind" \
  "$TARGET/train_data/cape" \
  "$TARGET/train_data/ir" \
  "$TARGET/train_data/lightning" \
  "$TARGET/train_data/hydro" \
  "$TARGET/train_data/dataset" \
  "$TARGET/train_data/cloud" \
  "$TARGET/train_data/models" \
  "$TARGET/data" \
  "$TARGET/plots"

sudo chown -R "$USER:$USER" "$TARGET"

CURRENT_PHASE="Phase 7 — Systemd-Units"
log_info "[Phase 7] Systemd-Units"

if [[ "$ENABLE_SERVICES" == true ]]; then
  sudo cp "$TARGET/wetterprojekt.service" /etc/systemd/system/

  if [[ -f "$TARGET/wetterprojekt-scheduler.service" ]]; then
    sudo cp "$TARGET/wetterprojekt-scheduler.service" /etc/systemd/system/
    SERVICE_SCHEDULER_PRESENT=true
  else
    log_warn "scheduler.service nicht gefunden, überspringe — ggf. Prompt 10 ausführen."
  fi

  sudo systemctl daemon-reload
  sudo systemctl enable --now wetterprojekt.service

  if [[ "$SERVICE_SCHEDULER_PRESENT" == true ]]; then
    sudo systemctl enable --now wetterprojekt-scheduler.service
  fi

  systemctl status --no-pager --lines=5 wetterprojekt.service || true
  if [[ "$SERVICE_SCHEDULER_PRESENT" == true ]]; then
    systemctl status --no-pager --lines=5 wetterprojekt-scheduler.service || true
  fi
else
  log_info "Services nicht aktiviert (Flag --enable-services nicht gesetzt)."
fi

CURRENT_PHASE="Phase 8 — Verifikation und Abschluss-Report"
log_info "[Phase 8] Verifikation und Abschluss-Report"

python3 - <<'PY'
import importlib
modules = ["cv2", "tensorflow", "lightgbm", "sklearn", "joblib", "pandas", "apscheduler"]
missing = []
for name in modules:
    try:
        importlib.import_module(name)
    except Exception:
        missing.append(name)
for name in missing:
    print(f"[WARN] Python-Import fehlt: {name}")
PY

COMMIT_SHA="$(git rev-parse --short HEAD)"
PY_VER="$(python3 --version)"
pip freeze > /tmp/wetterprojekt_pipfreeze.txt

echo
printf "${GREEN}✅ Repo:${NC} %s @ %s\n" "$BRANCH" "$COMMIT_SHA"
printf "${GREEN}✅ venv:${NC} %s/venv\n" "$TARGET"
printf "${GREEN}✅ Dependencies:${NC} %s apt-Installversuche erfolgreich\n" "$DEPENDENCIES_INSTALLED"
printf "${GREEN}✅ Verzeichnisse:${NC} angelegt/vorhanden\n"
if [[ "$ENABLE_SERVICES" == true ]]; then
  printf "${GREEN}✅ Services:${NC} enabled\n"
else
  printf "${YELLOW}✅ Services:${NC} nicht aktiviert\n"
fi
printf "${GREEN}✅ Python:${NC} %s\n" "$PY_VER"
printf "${GREEN}✅ Pip-Freeze:${NC} /tmp/wetterprojekt_pipfreeze.txt\n"

echo
cat <<'NEXTSTEPS'
Nächste Schritte:
  Modelle initial trainieren:  source venv/bin/activate && python3 dataset_builder.py && python3 model_training.py
  Status der Services:         sudo systemctl status wetterprojekt
  Logs live:                   journalctl -fu wetterprojekt
NEXTSTEPS
