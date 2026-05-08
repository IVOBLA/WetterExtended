#!/usr/bin/env bash
# ==============================================================================
# Wetterprojekt — install.sh
# Vollständiges Setup für Raspberry Pi 5 + Hailo-8
# Modus: full = komplette Neuinstallation | upgrade = nur Source aktualisieren
# ==============================================================================
set -euo pipefail

# --- Konstanten ---------------------------------------------------------------
DEFAULT_REPO_URL="https://github.com/<user>/wetterprojekt.git"
DEFAULT_BRANCH="main"
DEFAULT_TARGET="/home/ki-pi/wetterprojekt"
LOCK_FILE="/tmp/wetterprojekt_install.lock"
MIN_DISK_GB=10
MIN_RAM_MB=4096
PYTHON_MIN="3.10"
NODE_MIN=20

# --- Farben -------------------------------------------------------------------
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log_info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }
log_step()  { echo -e "\n${GREEN}══ $* ══${NC}"; }
MANUAL_STEPS=()
note_manual() { MANUAL_STEPS+=("  • $*"); }

# --- Optionen -----------------------------------------------------------------
CURRENT_PHASE="Init"
MODE="upgrade"
LOCAL_INSTALL=false
LOCAL_SOURCE=""
INSTALL_HAILO=true
INSTALL_NODE=true
SYSTEM_DEPS_ENABLED=true
ENABLE_SERVICES=false
BRANCH="$DEFAULT_BRANCH"
REPO="$DEFAULT_REPO_URL"
TARGET="$DEFAULT_TARGET"
APT_UPDATED=false
SERVICE_USER="$(id -un)"

# --- Trap / Lock --------------------------------------------------------------
cleanup_lock() { rm -f "$LOCK_FILE"; }
on_error() {
    local exit_code=$?
    log_error "Fehler in Phase: ${CURRENT_PHASE} (Exit-Code: ${exit_code})"
    [[ ${#MANUAL_STEPS[@]} -gt 0 ]] && {
        echo -e "\n${YELLOW}Manuelle Schritte die noch nötig sind:${NC}"
        for s in "${MANUAL_STEPS[@]}"; do echo "$s"; done
    }
    exit "$exit_code"
}
trap on_error ERR
trap cleanup_lock EXIT
[[ -e "$LOCK_FILE" ]] && { log_error "Lock-Datei existiert. Läuft bereits eine Installation?"; exit 1; }
touch "$LOCK_FILE"

# --- Usage --------------------------------------------------------------------
usage() { cat <<USAGE
Verwendung: $0 [OPTIONEN]

  --branch <name>       Git-Branch (Default: ${DEFAULT_BRANCH})
  --repo <url>          Repository-URL
  --target <pfad>       Zielpfad (Default: ${DEFAULT_TARGET})
  --mode <full|upgrade> full = alles neu, upgrade = nur Source (Default: upgrade)
  --enable-services     systemd-Services aktivieren
  --no-system-deps      apt-Installationen überspringen
  --no-hailo            Hailo-8-Setup überspringen
  --no-node             Node.js/Frontend-Build überspringen
  --local               Installiert aus dem lokalen Verzeichnis (ZIP-Modus).
                        Kein git clone nötig. Dateien werden nach --target kopiert.
  --help                Diese Hilfe

Modus-Unterschied:
  full    Löscht train_data/, venv/, frontend/dist/ und installiert alles neu.
          Prüft Systemzustand, OS-Version, Kernel, Festplatte, RAM.
  upgrade Aktualisiert nur den Source-Code, behält Daten und Modelle.
USAGE
}

# --- Argument-Parsing ---------------------------------------------------------
CURRENT_PHASE="Phase 1 — Argument-Parsing"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --branch)         BRANCH="$2"; shift 2 ;;
        --repo)           REPO="$2"; shift 2 ;;
        --target)         TARGET="$2"; shift 2 ;;
        --mode)           MODE="$2"
                          [[ "$MODE" == "full" || "$MODE" == "upgrade" ]] || {
                              log_error "--mode muss 'full' oder 'upgrade' sein."; exit 1; }
                          shift 2 ;;
        --enable-services) ENABLE_SERVICES=true; shift ;;
        --no-system-deps) SYSTEM_DEPS_ENABLED=false; shift ;;
        --no-hailo)       INSTALL_HAILO=false; shift ;;
        --no-node)        INSTALL_NODE=false; shift ;;
        --local)
            LOCAL_INSTALL=true
            LOCAL_SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
            shift ;;
        --help)           usage; exit 0 ;;
        *)                log_error "Unbekanntes Argument: $1"; usage; exit 1 ;;
    esac
done

if [[ -f "$TARGET/object_tracking.py" && ! -d "$TARGET/.git" ]] || [[ -f "./object_tracking.py" && ! -d "./.git" ]]; then
    LOCAL_INSTALL=true
    LOCAL_SOURCE="$(pwd)"
    log_info "ZIP/Ordner-Modus automatisch erkannt."
fi

# ==============================================================================
# PHASE 2 — Systemzustand prüfen (nur bei full)
# ==============================================================================
CURRENT_PHASE="Phase 2 — Systemzustand prüfen"
log_step "Phase 2 — Systemzustand prüfen"

# Hilfsfunktionen
check_ok()   { echo -e "  ${GREEN}✅${NC} $1"; }
check_warn() { echo -e "  ${YELLOW}⚠️ ${NC} $1"; }
check_fail() { echo -e "  ${RED}❌${NC} $1"; }

# OS-Version
if [[ -f /etc/os-release ]]; then
    OS_ID=$(. /etc/os-release; echo "$ID")
    OS_VER=$(. /etc/os-release; echo "$VERSION_CODENAME")
    if [[ "$OS_ID" == "raspbian" || "$OS_ID" == "debian" ]] && [[ "$OS_VER" == "bookworm" ]]; then
        check_ok "OS: $OS_ID $OS_VER"
    else
        check_warn "OS: $OS_ID $OS_VER — empfohlen ist Raspberry Pi OS Bookworm"
    fi
fi

# Raspberry Pi 5 erkennen
PI_MODEL=""
[[ -f /proc/device-tree/model ]] && PI_MODEL=$(cat /proc/device-tree/model 2>/dev/null || true)
if echo "$PI_MODEL" | grep -q "Raspberry Pi 5"; then
    check_ok "Hardware: $PI_MODEL"
    IS_PI5=true
else
    check_warn "Hardware: '$PI_MODEL' — kein Raspberry Pi 5 erkannt; Hailo-Setup übersprungen"
    IS_PI5=false
    INSTALL_HAILO=false
fi

# Kernel-Version
KERNEL=$(uname -r)
KERNEL_MAJOR=$(echo "$KERNEL" | cut -d. -f1)
KERNEL_MINOR=$(echo "$KERNEL" | cut -d. -f2)
if [[ "$KERNEL_MAJOR" -gt 6 || ( "$KERNEL_MAJOR" -eq 6 && "$KERNEL_MINOR" -ge 6 ) ]]; then
    check_ok "Kernel: $KERNEL"
else
    check_warn "Kernel: $KERNEL — empfohlen >= 6.6 für Hailo PCIe-Support"
fi

# Festplattenplatz
AVAIL_GB=$(df -BG "$HOME" | awk 'NR==2{gsub("G","",$4); print $4}')
if [[ "$AVAIL_GB" -ge "$MIN_DISK_GB" ]]; then
    check_ok "Festplatte: ${AVAIL_GB} GB verfügbar"
else
    check_fail "Festplatte: nur ${AVAIL_GB} GB frei — mind. ${MIN_DISK_GB} GB empfohlen"
    if [[ "$MODE" == "full" ]]; then
        log_error "Zu wenig Speicherplatz für Vollinstallation."
        exit 1
    fi
fi

# RAM
TOTAL_RAM_MB=$(awk '/MemTotal/{printf "%d", $2/1024}' /proc/meminfo)
if [[ "$TOTAL_RAM_MB" -ge "$MIN_RAM_MB" ]]; then
    check_ok "RAM: ${TOTAL_RAM_MB} MB"
else
    check_warn "RAM: ${TOTAL_RAM_MB} MB — empfohlen mind. ${MIN_RAM_MB} MB"
fi

# Netzwerk
if curl -s --max-time 5 https://pypi.org > /dev/null 2>&1; then
    check_ok "Netzwerk: Internetzugang vorhanden"
else
    check_fail "Netzwerk: kein Internetzugang — Installation kann nicht fortfahren"
    exit 1
fi

# Python-Version
if command -v python3 &>/dev/null; then
    PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    PY_OK=$(python3 -c "import sys; print('ok' if sys.version_info >= (3,10) else 'fail')")
    if [[ "$PY_OK" == "ok" ]]; then
        check_ok "Python: $PY_VER"
    else
        check_fail "Python: $PY_VER — mind. $PYTHON_MIN erforderlich"
        exit 1
    fi
else
    check_fail "Python3 nicht gefunden"
    exit 1
fi

# PCIe Gen3 (nur Pi 5)
if [[ "$IS_PI5" == "true" ]] && [[ -f /boot/firmware/config.txt ]]; then
    if grep -q "^dtparam=pciex1_gen=3" /boot/firmware/config.txt; then
        check_ok "PCIe Gen3: aktiviert"
    else
        check_warn "PCIe Gen3: nicht in /boot/firmware/config.txt — für Hailo erforderlich"
        PCIE_NEEDS_ENABLE=true
    fi
fi

# Hailo-Treiber
if command -v hailortcli &>/dev/null; then
    HAILO_VER=$(hailortcli --version 2>/dev/null | head -1 || echo "unbekannt")
    check_ok "Hailo-Treiber: $HAILO_VER"
    HAILO_DRIVER_OK=true
else
    check_warn "Hailo-Treiber: hailortcli nicht gefunden — wird in Phase 7b installiert"
    HAILO_DRIVER_OK=false
fi

# Node.js
if command -v node &>/dev/null; then
    NODE_VER=$(node --version | sed 's/v//')
    NODE_MAJOR=$(echo "$NODE_VER" | cut -d. -f1)
    if [[ "$NODE_MAJOR" -ge "$NODE_MIN" ]]; then
        check_ok "Node.js: v$NODE_VER"
        NODE_OK=true
    else
        check_warn "Node.js: v$NODE_VER — mind. v${NODE_MIN} erforderlich; wird aktualisiert"
        NODE_OK=false
    fi
else
    check_warn "Node.js: nicht gefunden — wird in Phase 7c installiert"
    NODE_OK=false
fi

# ==============================================================================
# PHASE 3 — Source holen
# ==============================================================================
CURRENT_PHASE="Phase 3 — Source holen"
log_step "Phase 3 — Source holen"

if [[ "$LOCAL_INSTALL" == true ]]; then
    log_info "Lokale Installation aus: $LOCAL_SOURCE"
    if [[ "$LOCAL_SOURCE" != "$TARGET" ]]; then
        mkdir -p "$TARGET"
        cp -a "$LOCAL_SOURCE/." "$TARGET/"
        log_info "Quellcode nach $TARGET kopiert."
    else
        log_info "Bereits im Zielverzeichnis — kein Kopieren nötig."
    fi
    cd "$TARGET"
elif [[ -d "$TARGET/.git" ]]; then
    cd "$TARGET"
    git fetch --all
    git checkout "$BRANCH"
    git pull --ff-only
    log_info "Repository aktualisiert: $(git rev-parse --short HEAD)"
else
    if [[ "$REPO" == *"<user>"* ]]; then
        log_error "Placeholder-URL erkannt: $REPO"
        log_error "Bitte --repo <echte-url> angeben oder --local verwenden."
        exit 1
    fi
    git clone --branch "$BRANCH" "$REPO" "$TARGET"
    cd "$TARGET"
    log_info "Repository geklont: $(git rev-parse --short HEAD)"
fi

# ==============================================================================
# PHASE 3b — Vollinstallation: Daten und Build löschen
# ==============================================================================
CURRENT_PHASE="Phase 3b — Modus"
log_step "Phase 3b — Modus: $MODE"

if [[ "$MODE" == "full" ]]; then
    log_warn "VOLLINSTALLATION — folgende Verzeichnisse werden gelöscht:"
    log_warn "  ${TARGET}/train_data/  (Trainingsdaten + Modelle)"
    log_warn "  ${TARGET}/venv/        (Python-Umgebung)"
    log_warn "  ${TARGET}/frontend/dist/ (Frontend-Build)"
    log_warn "  ${TARGET}/data/        (Radar-Cache)"
    read -r -p "  Wirklich fortfahren? (yes/NO) " confirm
    if [[ "$confirm" != "yes" ]]; then
        log_warn "Abgebrochen — wechsle in upgrade-Modus."
        MODE="upgrade"
    else
        # Services stoppen damit keine Dateien gesperrt sind
        for svc in wetterprojekt wetterprojekt-scheduler wetterprojekt-admin; do
            systemctl is-active --quiet "$svc" 2>/dev/null && sudo systemctl stop "$svc" && log_info "Service gestoppt: $svc" || true
        done
        rm -rf "${TARGET}/train_data" "${TARGET}/venv" "${TARGET}/frontend/dist" "${TARGET}/data" "${TARGET}/plots" || true
        log_info "Daten gelöscht."
    fi
else
    log_info "Upgrade-Modus: Trainingsdaten und Modelle bleiben erhalten."
fi

# ==============================================================================
# PHASE 4 — System-Dependencies (apt)
# ==============================================================================
CURRENT_PHASE="Phase 4 — System-Dependencies"
log_step "Phase 4 — System-Dependencies"

if [[ "$SYSTEM_DEPS_ENABLED" == true ]]; then
    log_info "Aktualisiere Paketliste..."
    sudo apt-get update -qq && APT_UPDATED=true

    APT_PKGS=(
        python3-venv python3-dev python3-pip
        git curl wget build-essential
        libgdal-dev gdal-bin           # für rasterio
        libatlas-base-dev              # NumPy BLAS auf Pi
        libopencv-dev                  # OpenCV system-libs
        libhdf5-dev                    # TensorFlow h5
        libffi-dev libssl-dev          # pip wheel builds
        libjpeg-dev zlib1g-dev         # Pillow
        ffmpeg                         # movement.gif
    )

    log_info "Installiere APT-Pakete: ${APT_PKGS[*]}"
    sudo apt-get install -y "${APT_PKGS[@]}" 2>&1 | grep -E "^(Inst|Err)" || true
    log_info "APT-Pakete installiert."
else
    log_warn "APT übersprungen (--no-system-deps)."
fi

# ==============================================================================
# PHASE 5 — Python venv + pip-Pakete
# ==============================================================================
CURRENT_PHASE="Phase 5 — Python venv"
log_step "Phase 5 — Python venv und pip-Pakete"

VENV="$TARGET/venv"
if [[ ! -d "$VENV" ]]; then
    python3 -m venv "$VENV"
    log_info "venv erstellt: $VENV"
else
    log_info "venv vorhanden: $VENV"
fi

"$VENV/bin/pip" install --upgrade pip wheel setuptools -q

log_info "Installiere requirements.txt..."
if "$VENV/bin/pip" install -r "$TARGET/requirements.txt" \
        --extra-index-url https://www.piwheels.org/simple \
        2>&1 | tail -5; then
    log_info "pip-Pakete installiert."
else
    log_warn "pip install hatte Fehler — bitte manuell prüfen:"
    note_manual "cd $TARGET && source venv/bin/activate && pip install -r requirements.txt"
fi

# ==============================================================================
# PHASE 6 — Verzeichnisstruktur anlegen + .env prüfen
# ==============================================================================
CURRENT_PHASE="Phase 6 — Verzeichnisstruktur"
log_step "Phase 6 — Verzeichnisstruktur und .env"

DIRS=(
    train_data/radar train_data/objects train_data/weather
    train_data/wind train_data/cape train_data/dataset
    train_data/models/current train_data/ir train_data/lightning
    train_data/evaluation train_data/cloud
    train_data/arome          # NEU: AROME icon_d2 Gitterpunktdaten
    data logs
)
for d in "${DIRS[@]}"; do
    mkdir -p "$TARGET/$d"
done
log_info "Verzeichnisstruktur erstellt."

INITIAL_MODEL_SOURCE="$TARGET/weather_lstm_model.keras"
INITIAL_MODEL_TARGET="$TARGET/train_data/models/current/weather_lstm.keras"
if [[ -f "$INITIAL_MODEL_SOURCE" && ! -f "$INITIAL_MODEL_TARGET" ]]; then
    cp "$INITIAL_MODEL_SOURCE" "$INITIAL_MODEL_TARGET"
    log_info "Initialmodell kopiert: $INITIAL_MODEL_TARGET"
fi

# .env prüfen / erstellen
ENV_FILE="$TARGET/.env"
if [[ ! -f "$ENV_FILE" ]]; then
    if [[ -f "$TARGET/.env.example" ]]; then
        cp "$TARGET/.env.example" "$ENV_FILE"
        log_warn ".env aus .env.example erstellt — FTP-Credentials eintragen:"
        note_manual "nano $ENV_FILE  # FTP_SERVER, FTP_USER, FTP_PASS, FTP_PATH setzen"
    else
        cat > "$ENV_FILE" <<'ENVTEMPLATE'
FTP_SERVER=
FTP_USER=
FTP_PASS=
FTP_PATH=/wetterAI/
ENVTEMPLATE
        log_warn ".env angelegt — FTP-Credentials fehlen noch:"
        note_manual "nano $ENV_FILE  # FTP_SERVER, FTP_USER, FTP_PASS, FTP_PATH setzen"
    fi
else
    # Prüfen ob Credentials gesetzt sind
    FTP_OK=true
    for var in FTP_SERVER FTP_USER FTP_PASS; do
        val=$(grep "^${var}=" "$ENV_FILE" | cut -d= -f2 | tr -d ' ')
        [[ -z "$val" ]] && { FTP_OK=false; break; }
    done
    if [[ "$FTP_OK" == "true" ]]; then
        check_ok ".env: FTP-Credentials konfiguriert"
    else
        check_warn ".env: FTP-Credentials unvollständig"
        note_manual "nano $ENV_FILE  # FTP_SERVER, FTP_USER, FTP_PASS prüfen"
    fi
fi

# ==============================================================================
# PHASE 7b — Hailo-8-Installation
# ==============================================================================
CURRENT_PHASE="Phase 7b — Hailo-8"
log_step "Phase 7b — Hailo-8-Installation"

if [[ "$INSTALL_HAILO" == true && "$IS_PI5" == "true" ]]; then

    # PCIe Gen3 aktivieren
    if [[ "${PCIE_NEEDS_ENABLE:-false}" == "true" ]]; then
        if [[ -w /boot/firmware/config.txt ]]; then
            echo "dtparam=pciex1_gen=3" | sudo tee -a /boot/firmware/config.txt > /dev/null
            log_warn "PCIe Gen3 in config.txt aktiviert — REBOOT nach Installation erforderlich!"
            NEEDS_REBOOT=true
        else
            note_manual "echo 'dtparam=pciex1_gen=3' | sudo tee -a /boot/firmware/config.txt"
        fi
    fi

    # Hailo APT-Repository
    if [[ ! -f /etc/apt/sources.list.d/hailo.list ]]; then
        log_info "Füge Hailo-APT-Repository hinzu..."
        if curl -fsSL https://hailo.ai/developer-zone/sw-downloads/raspi-key.gpg 2>/dev/null \
                | sudo tee /etc/apt/trusted.gpg.d/hailo.gpg > /dev/null; then
            echo "deb https://hailo.ai/developer-zone/sw-downloads/raspbian bookworm main" \
                | sudo tee /etc/apt/sources.list.d/hailo.list
            sudo apt-get update -qq
            APT_UPDATED=true
        else
            log_warn "Hailo GPG-Key konnte nicht geladen werden."
            note_manual "Hailo-Treiber manuell installieren — siehe HAILO_INSTALL.md"
        fi
    fi

    # hailo-all Paket
    if ! dpkg -s hailo-all &>/dev/null; then
        log_info "Installiere hailo-all..."
        if sudo apt-get install -y hailo-all 2>/dev/null; then
            check_ok "hailo-all installiert — Reboot erforderlich!"
            NEEDS_REBOOT=true
        else
            log_warn "hailo-all Installation fehlgeschlagen."
            note_manual "sudo apt install hailo-all  (dann sudo reboot)"
        fi
    else
        check_ok "hailo-all bereits installiert: $(dpkg -s hailo-all | grep Version | cut -d' ' -f2)"
    fi

    # Python-Bindings
    if ! "$VENV/bin/pip" show hailo-platform &>/dev/null; then
        log_info "Installiere hailo-platform Python-Bindings..."
        if "$VENV/bin/pip" install hailo-platform -q 2>/dev/null; then
            check_ok "hailo-platform installiert"
        else
            log_warn "hailo-platform pip-Install fehlgeschlagen (Treiber muss zuerst installiert sein)."
            note_manual "Nach Reboot: source venv/bin/activate && pip install hailo-platform"
        fi
    else
        check_ok "hailo-platform bereits installiert"
    fi

    # Verifikation
    if command -v hailortcli &>/dev/null; then
        HAILO_DEV=$(hailortcli scan 2>/dev/null | grep -c "Device" || echo "0")
        if [[ "$HAILO_DEV" -gt 0 ]]; then
            check_ok "Hailo-Gerät erkannt: $HAILO_DEV Device(s)"
        else
            check_warn "hailortcli verfügbar, aber kein Gerät erkannt — Reboot ausstehend?"
        fi
    fi

else
    if [[ "$INSTALL_HAILO" == false ]]; then
        log_info "Hailo übersprungen (--no-hailo)."
    else
        log_info "Hailo übersprungen (kein Pi 5 erkannt)."
    fi
fi

# ==============================================================================
# PHASE 7c — Node.js + Frontend-Build
# ==============================================================================
CURRENT_PHASE="Phase 7c — Node.js + Frontend"
log_step "Phase 7c — Node.js + Frontend-Build"

if [[ "$INSTALL_NODE" == true ]]; then

    # Node.js installieren oder aktualisieren
    if [[ "${NODE_OK:-false}" == "false" ]]; then
        log_info "Installiere Node.js $NODE_MIN..."
        if curl -fsSL https://deb.nodesource.com/setup_${NODE_MIN}.x 2>/dev/null \
                | sudo -E bash - && sudo apt-get install -y nodejs 2>/dev/null; then
            check_ok "Node.js installiert: $(node --version)"
            NODE_OK=true
        else
            log_warn "Node.js Installation fehlgeschlagen."
            note_manual "curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt install -y nodejs"
        fi
    else
        check_ok "Node.js bereits OK: $(node --version)"
    fi

    # Frontend bauen
    if [[ -f "$TARGET/frontend/package.json" ]] && [[ "${NODE_OK:-false}" == "true" ]]; then
        cd "$TARGET/frontend"

        log_info "npm install..."
        if npm install --no-audit --no-fund 2>&1 | tail -3; then
            log_info "npm run build..."
            if NODE_OPTIONS="--max-old-space-size=2048" npm run build 2>&1 | tail -5; then
                check_ok "Frontend-Build erfolgreich: frontend/dist/"
            else
                log_warn "Frontend-Build fehlgeschlagen."
                note_manual "cd $TARGET/frontend && npm run build"
            fi
        else
            log_warn "npm install fehlgeschlagen."
            note_manual "cd $TARGET/frontend && npm install && npm run build"
        fi
        cd "$TARGET"
    else
        [[ ! -f "$TARGET/frontend/package.json" ]] && check_warn "frontend/package.json nicht gefunden"
    fi

else
    log_info "Node.js/Frontend übersprungen (--no-node)."
    note_manual "cd $TARGET/frontend && npm install && npm run build"
fi

# ==============================================================================
# PHASE 7 — systemd-Services
# ==============================================================================
CURRENT_PHASE="Phase 7 — systemd-Services"
log_step "Phase 7 — systemd-Services"

if [[ "$ENABLE_SERVICES" == true ]]; then
    for svc_file in wetterprojekt.service wetterprojekt-scheduler.service wetterprojekt-admin.service; do
        src="$TARGET/$svc_file"
        if [[ -f "$src" ]]; then
            tmp="$TARGET/.generated-$svc_file"
            sed -e "s|^WorkingDirectory=.*|WorkingDirectory=$TARGET|g" \
                -e "s|^User=.*|User=$SERVICE_USER|g" \
                -e "s|/home/ki-pi/wetterprojekt|$TARGET|g" \
                "$src" > "$tmp"
        fi
    done
    sudo systemctl daemon-reload
    for svc_file in wetterprojekt.service wetterprojekt-scheduler.service wetterprojekt-admin.service; do
        generated="$TARGET/.generated-$svc_file"
        if [[ -f "$generated" ]]; then
            sudo cp "$generated" "/etc/systemd/system/$svc_file"
            svc_name="${svc_file}"
            sudo systemctl enable "$svc_name" || true
            sudo systemctl restart "$svc_name" || true
            systemctl is-active --quiet "$svc_name" \
                && check_ok "Service aktiv: $svc_name" \
                || check_warn "Service konnte nicht gestartet werden: $svc_name"
        else
            check_warn "Service-Datei nicht gefunden: $svc_file"
        fi
    done
else
    log_warn "Services werden nicht aktiviert (--enable-services nicht gesetzt)."
    note_manual "sudo systemctl daemon-reload && sudo systemctl enable --now wetterprojekt wetterprojekt-scheduler wetterprojekt-admin"
fi

# ==============================================================================
# PHASE 8 — Abschluss-Report
# ==============================================================================
CURRENT_PHASE="Phase 8 — Abschluss-Report"
log_step "Phase 8 — Abschluss-Report"

echo ""
echo "════════════════════════════════════════════"
printf "  ${GREEN}%-20s${NC} %s\n" "Modus:"       "$MODE"
printf "  ${GREEN}%-20s${NC} %s\n" "Branch:"      "$(cd "$TARGET" && git rev-parse --abbrev-ref HEAD) @ $(cd "$TARGET" && git rev-parse --short HEAD)"
printf "  ${GREEN}%-20s${NC} %s\n" "Python:"      "$("$VENV/bin/python3" --version 2>&1)"
printf "  ${GREEN}%-20s${NC} %s\n" "Node.js:"     "$(node --version 2>/dev/null || echo 'nicht installiert')"
printf "  ${GREEN}%-20s${NC} %s\n" "Frontend:"    "$([ -f \"$TARGET/frontend/dist/index.html\" ] && echo 'gebaut ✅' || echo 'fehlt ❌')"
printf "  ${GREEN}%-20s${NC} %s\n" "Hailo:"       "$(command -v hailortcli &>/dev/null && hailortcli --version 2>/dev/null | head -1 || echo 'nicht installiert')"
printf "  ${GREEN}%-20s${NC} %s\n" ".env:"        "$([ -f \"$TARGET/.env\" ] && echo 'vorhanden' || echo 'fehlt')"
echo "════════════════════════════════════════════"

# Manuelle Schritte ausgeben
if [[ ${#MANUAL_STEPS[@]} -gt 0 ]]; then
    echo ""
    echo -e "${YELLOW}⚠️  Manuelle Schritte erforderlich:${NC}"
    for s in "${MANUAL_STEPS[@]}"; do echo -e "$s"; done
fi

# Reboot-Hinweis
if [[ "${NEEDS_REBOOT:-false}" == "true" ]]; then
    echo ""
    echo -e "${YELLOW}🔄 REBOOT ERFORDERLICH für Hailo-Treiber:${NC}"
    echo "   sudo reboot"
fi

# Nächste Schritte
cat <<'NEXTSTEPS'

Nächste Schritte nach Abschluss:
  1. .env befüllen (FTP-Credentials):
       nano /home/ki-pi/wetterprojekt/.env

  2. Services aktivieren (falls --enable-services nicht gesetzt war):
       sudo systemctl daemon-reload
       sudo systemctl enable --now wetterprojekt wetterprojekt-scheduler wetterprojekt-admin

  3. Erstes Training starten (nach Datensammlung ~1h):
       source /home/ki-pi/wetterprojekt/venv/bin/activate
       python3 dataset_builder.py && python3 model_training.py

  4. Adminpanel öffnen:
       http://<pi-ip>:5000/

  5. Logs live:
       journalctl -fu wetterprojekt
NEXTSTEPS
