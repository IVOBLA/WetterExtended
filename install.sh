#!/usr/bin/env bash
# ==============================================================================
# Wetterprojekt — install.sh
# Vollständiges Setup für Raspberry Pi 5 + Hailo-8
# Modus: full = komplette Neuinstallation | upgrade = nur Source aktualisieren
# ==============================================================================
set -euo pipefail

# --- Konstanten ---------------------------------------------------------------
DEFAULT_REPO_URL="git@github.com:IVOBLA/WetterExtended.git"
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

# --- Git / GitHub --------------------------------------------------------------
# Standard: GitHub per SSH verwenden. Damit werden keine Passwörter oder Tokens
# in URLs, Shell-History oder Logs geschrieben.
if [[ -z "${GIT_SSH_COMMAND:-}" ]]; then
    export GIT_SSH_COMMAND="ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10"
fi

is_ssh_repo_url() {
    [[ "$1" == git@github.com:* || "$1" == ssh://git@github.com/* ]]
}

github_ssh_preflight() {
    # Nur für SSH-URLs prüfen. HTTPS bleibt möglich, wird aber von GitHub
    # bei privaten Repos nur mit Token funktionieren.
    if ! is_ssh_repo_url "$REPO"; then
        log_warn "Repo-URL ist keine SSH-URL: $REPO"
        log_warn "Empfohlen: git@github.com:IVOBLA/WetterExtended.git"
        return 0
    fi

    if ! command -v ssh &>/dev/null; then
        log_error "ssh ist nicht installiert. Bitte openssh-client installieren."
        exit 1
    fi

    log_info "Prüfe GitHub-SSH-Authentifizierung..."
    set +e
    SSH_OUT=$(ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -T git@github.com 2>&1)
    SSH_RC=$?
    set -e

    # GitHub liefert bei erfolgreicher Authentifizierung oft Exit-Code 1,
    # weil kein Shell-Zugriff bereitgestellt wird. Entscheidend ist der Text.
    if echo "$SSH_OUT" | grep -qi "successfully authenticated"; then
        check_ok "GitHub SSH: authentifiziert"
        return 0
    fi

    log_error "GitHub SSH-Authentifizierung fehlgeschlagen."
    echo "$SSH_OUT" >&2
    echo "" >&2
    log_error "Prüfen:"
    log_error "  ssh -T git@github.com"
    log_error "  cat ~/.ssh/id_ed25519.pub"
    log_error "  GitHub → Settings → SSH and GPG keys"
    exit 1
}

# --- Optionen -----------------------------------------------------------------
CURRENT_PHASE="Init"
MODE="upgrade"
NO_HAILO=0
NO_NODE=0
LOCAL_INSTALL=false
LOCAL_SOURCE=""
INSTALL_HAILO=true
INSTALL_NODE=true
SYSTEM_DEPS_ENABLED=true
ENABLE_SERVICES=false
LOCAL_TRAINING_FLAG=true          # --no-training setzt auf false (Phase B)
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
  --repo <url>          Repository-URL (Default SSH: ${DEFAULT_REPO_URL})
  --target <pfad>       Zielpfad (Default: ${DEFAULT_TARGET})
  --mode <full|upgrade> full = alles neu, upgrade = nur Source (Default: upgrade)
  --enable-services     systemd-Services aktivieren
  --no-system-deps      apt-Installationen überspringen
  --no-hailo            Hailo-8-Setup überspringen
  --no-node             Node.js/Frontend-Build überspringen
  --no-training         LOCAL_TRAINING=False setzen (Phase B: Training auf Linux-Rechner)
  --local               Installiert aus dem lokalen Verzeichnis (ZIP-Modus).
                        Kein git clone nötig. Dateien werden nach --target kopiert.
  --help                Diese Hilfe

SSH-Beispiel:
  ./install.sh --repo git@github.com:IVOBLA/WetterExtended.git --mode upgrade

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
        --no-hailo)       INSTALL_HAILO=false; NO_HAILO=1; shift ;;
        --no-node)        INSTALL_NODE=false; NO_NODE=1; shift ;;
        --no-training)    LOCAL_TRAINING_FLAG=false; shift ;;
        --local)
            LOCAL_INSTALL=true
            LOCAL_SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
            shift ;;
        --help|-h)
                          echo ""
                          echo "WetterExtended install.sh"
                          echo ""
                          echo "Verwendung: bash install.sh [OPTIONEN]"
                          echo ""
                          echo "  --mode=upgrade   Nur Source-Code aktualisieren (DEFAULT)"
                          echo "                   Modelle + Trainingsdaten bleiben erhalten."
                          echo "                   Python/Node-Pakete + systemd-Services werden aktualisiert."
                          echo ""
                          echo "  --mode=full      KOMPLETTE NEUINSTALLATION"
                          echo "                   ⚠️  LÖSCHT alle Trainingsmodelle und Radar-Daten!"
                          echo "                   Folgende Verzeichnisse werden geleert:"
                          echo "                     ~/wetterprojekt/train_data/models/"
                          echo "                     ~/wetterprojekt/train_data/radar/"
                          echo "                     ~/wetterprojekt/train_data/objects/"
                          echo "                     ~/wetterprojekt/train_data/dataset/"
                          echo "                     ~/wetterprojekt/train_data/weather/"
                          echo "                     ~/wetterprojekt/train_data/dem_cache/"
                          echo "                   Konfiguration (.env, runtime_overrides.json),"
                          echo "                   DEM-Tiles und train_data/cell_filters/"
                          echo "                   (HitL-Filter + Polygon-PNGs) bleiben erhalten."
                          echo "                   evaluation/-Logs und systemd-Journal werden geleert."
                          echo ""
                          echo "  --no-hailo       Hailo-apt-Pakete nicht installieren"
                          echo "  --no-node        Node.js/npm nicht installieren (kein Frontend-Build)"
                          echo "  --help           Diese Hilfe anzeigen"
                          echo ""
                          exit 0 ;;
        *)                log_error "Unbekanntes Argument: $1"; usage; exit 1 ;;
    esac
done

# Im full-Modus Services automatisch aktivieren
if [[ "$MODE" == "full" && "$ENABLE_SERVICES" == "false" ]]; then
    ENABLE_SERVICES=true
    log_info "Vollinstallation: --enable-services automatisch gesetzt."
fi

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$_SCRIPT_DIR/object_tracking.py" && ! -d "$_SCRIPT_DIR/.git" ]]; then
    LOCAL_INSTALL=true
    LOCAL_SOURCE="$_SCRIPT_DIR"
    log_info "ZIP/Ordner-Modus automatisch erkannt (Skriptverzeichnis: $_SCRIPT_DIR)."
elif [[ -f "$TARGET/object_tracking.py" && ! -d "$TARGET/.git" ]]; then
    LOCAL_INSTALL=true
    LOCAL_SOURCE="$TARGET"
    log_info "ZIP/Ordner-Modus automatisch erkannt (Zielverzeichnis bereits befüllt)."
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
# Generische Pi-Erkennung (alle Modelle — für piwheels u.a.)
if echo "$PI_MODEL" | grep -qi "Raspberry Pi"; then
    IS_PI=true
else
    IS_PI=false
fi

# Pi 5-spezifische Erkennung (Hailo, PCIe Gen3)
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
    github_ssh_preflight
    cd "$TARGET"

    CURRENT_REMOTE="$(git remote get-url origin 2>/dev/null || true)"
    if [[ -z "$CURRENT_REMOTE" ]]; then
        git remote add origin "$REPO"
        log_info "Git remote origin gesetzt: $REPO"
    elif [[ "$CURRENT_REMOTE" != "$REPO" ]]; then
        log_warn "Git remote origin wird angepasst:"
        log_warn "  alt: $CURRENT_REMOTE"
        log_warn "  neu: $REPO"
        git remote set-url origin "$REPO"
    fi

    git fetch origin "$BRANCH"

    if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
        git checkout "$BRANCH"
    else
        git checkout -B "$BRANCH" "origin/$BRANCH"
    fi

    if [[ "$MODE" == "full" ]]; then
        # Vollinstallation: lokalen Stand immer durch remote ersetzen.
        # git pull --ff-only würde bei divergierten Branches mit Exit 128 abbrechen.
        git reset --hard "origin/$BRANCH"
        log_info "Repository auf remote Stand zurückgesetzt: $(git rev-parse --short HEAD)"
    else
        # Upgrade: fast-forward versuchen; bei Divergenz klaren Fehlertext geben.
        if ! git pull --ff-only origin "$BRANCH"; then
            log_error "Fast-Forward nicht möglich — lokale Commits weichen von remote ab."
            log_error "Optionen:"
            log_error "  a) Lokale Commits verwerfen:  git reset --hard origin/$BRANCH"
            log_error "  b) Vollinstallation:          bash install.sh --mode=full"
            exit 1
        fi
        log_info "Repository aktualisiert: $(git rev-parse --short HEAD)"
    fi
else
    if [[ "$REPO" == *"<user>"* ]]; then
        log_error "Placeholder-URL erkannt: $REPO"
        log_error "Bitte --repo <echte-url> angeben oder --local verwenden."
        exit 1
    fi

    github_ssh_preflight
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
    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║         ⚠️   VOLLSTÄNDIGE NEUINSTALLATION (--mode=full)      ║"
    echo "║   ALLE TRAININGSMODELLE UND RADAR-DATEN WERDEN GELÖSCHT!    ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
    echo "Folgende Verzeichnisse werden vollstaendig geloescht:"
    echo "  train_data/models/      (ML-Modelle)"
    echo "  train_data/radar/       (Trainings-Radarbilder)"
    echo "  train_data/objects/     (Tracking-Daten)"
    echo "  train_data/dataset/     (ML-Dataset)"
    echo "  train_data/weather/     (Wetterdaten-Cache)"
    echo "  train_data/arome/       (AROME-Gitterpunktdaten)"
    echo "  train_data/api_cache/   (API-Response-Cache)"
    echo "  train_data/wind/        (700-hPa-Winddaten)"
    echo "  train_data/cape/        (CAPE-Daten)"
    echo "  train_data/cloud/       (Wolkenhoehendaten)"
    echo "  train_data/lightning/   (Blitzdaten)"
    echo "  train_data/ir/          (IR-Satellitenbilder)"
    echo "  train_data/ir_cells/    (IR-Zell-Schnitte)"
    echo "  train_data/evaluation/  (Logs und Genauigkeits-Historie)"
    echo "  data/radar/             (Live-Radarbilder fuer Animation)"
    echo "  data/overlay.png, latest.png, latest.kml, forecast.kmz"
    echo ""
    echo "NICHT geloescht werden:"
    echo "  train_data/dem/         (Copernicus DEM — grosser Einmal-Download)"
    echo "  .env                    (Zugangsdaten: FTP, Blitzortung, Twilio)"
    echo "  runtime_overrides.json  (Admin-Panel-Einstellungen)"
    echo ""
    printf "Fortfahren? Tippe 'ja' und drücke Enter: "
    read -r CONFIRM
    if [[ "$CONFIRM" != "ja" ]]; then
        echo "Abgebrochen."
        exit 1
    fi

    echo ""
    echo "[FULL] Stoppe Services..."
    sudo systemctl stop wetterprojekt wetterprojekt-scheduler wetterprojekt-admin 2>/dev/null || true
    sudo systemctl disable wetterprojekt wetterprojekt-scheduler wetterprojekt-admin 2>/dev/null || true

    # ── train_data: alle Datenverzeichnisse loeschen (NICHT dem/) ──────────────
    FULL_DELETE_DIRS=(
        "${TARGET}/train_data/models"
        "${TARGET}/train_data/radar"
        "${TARGET}/train_data/objects"
        "${TARGET}/train_data/dataset"
        "${TARGET}/train_data/weather"
        "${TARGET}/train_data/arome"
        "${TARGET}/train_data/api_cache"
        "${TARGET}/train_data/wind"
        "${TARGET}/train_data/cape"
        "${TARGET}/train_data/cloud"
        "${TARGET}/train_data/lightning"
        "${TARGET}/train_data/ir"
        "${TARGET}/train_data/ir_cells"
        "${TARGET}/train_data/evaluation"
        "${TARGET}/train_data/dem_cache"
    )
    for _dir in "${FULL_DELETE_DIRS[@]}"; do
        if [[ -d "$_dir" ]]; then
            echo "[FULL] Loesche: $(basename $_dir)/"
            rm -rf "$_dir"
        fi
    done

    # ── data/: Live-Dateien loeschen ───────────────────────────────────────────
    echo "[FULL] Loesche data/radar/ ..."
    rm -rf "${TARGET}/data/radar/"
    echo "[FULL] Loesche data/overlay.png, latest.png, latest.kml ..."
    rm -f  "${TARGET}/data/overlay.png"            "${TARGET}/data/latest.png"             "${TARGET}/data/latest.kml"             "${TARGET}/data/.kmz_last_modified"
    rm -f  "${TARGET}/forecast.kmz"            "${TARGET}/movement.gif"

    # ── venv und Frontend-Build loeschen (werden in Phase 5/7 neu gebaut) ──────
    echo "[FULL] Loesche venv/ ..."
    rm -rf "${TARGET}/venv"
    echo "[FULL] Loesche frontend/dist/ und frontend/node_modules/ ..."
    rm -rf "${TARGET}/frontend/dist"
    rm -rf "${TARGET}/frontend/node_modules"

    # ── DEM-Tiles bleiben erhalten ─────────────────────────────────────────────
    if [[ -d "${TARGET}/train_data/dem" ]]; then
        _dem_count=$(find "${TARGET}/train_data/dem" -name "*.tif" 2>/dev/null | wc -l)
        log_info "DEM-Tiles behalten: ${_dem_count} .tif-Dateien (Einmal-Download, ~1.4 GB)"
    fi

    echo "[FULL] Alle Daten geloescht. Weiter mit vollstaendiger Installation..."
    echo ""
else
    log_info "Upgrade-Modus: Trainingsdaten und Modelle bleiben erhalten."

    # Laufende Services stoppen — neuer Code + neue pip-Pakete werden erst
    # nach Neustart des Prozesses wirksam. Gestoppte Services werden am
    # Ende von Phase 8 automatisch wieder gestartet.
    _RUNNING_SERVICES=()
    for _svc in wetterprojekt wetterprojekt-scheduler wetterprojekt-admin; do
        if systemctl is-active --quiet "$_svc" 2>/dev/null; then
            _RUNNING_SERVICES+=("$_svc")
        fi
    done
    if [[ ${#_RUNNING_SERVICES[@]} -gt 0 ]]; then
        log_info "Stoppe Services vor Upgrade: ${_RUNNING_SERVICES[*]}"
        sudo systemctl stop "${_RUNNING_SERVICES[@]}" 2>/dev/null || true
        _RESTART_AFTER_UPGRADE=true
    else
        _RESTART_AFTER_UPGRADE=false
    fi
fi
# full-Modus: Flag initialisieren (Services werden über ENABLE_SERVICES behandelt)
[[ "$MODE" == "full" ]] && _RESTART_AFTER_UPGRADE=false

# ── HitL: Verzeichnisse für Cell Filters anlegen (beide Modi, idempotent) ────
# WICHTIG: train_data/cell_filters/ bleibt bei --mode=full ERHALTEN.
# Es enthält benutzergenerierte Lerndaten (manuelle Polygone, KI-Vorschläge,
# PNG-Ausschnitte) und wird analog zu .env, runtime_overrides.json und
# DEM-Tiles als geschützter Benutzerdaten-Bestand behandelt.
log_info "Stelle HitL-Verzeichnisse sicher (bestehende Daten bleiben unberührt)..."
mkdir -p "${TARGET}/train_data/cell_filters/polygons"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${TARGET}/train_data/cell_filters" 2>/dev/null || true
chmod 755 "${TARGET}/train_data/cell_filters" "${TARGET}/train_data/cell_filters/polygons" 2>/dev/null || true

# Status loggen
if [[ -f "${TARGET}/train_data/cell_filters/cell_filters.json" ]]; then
    _hitl_n=$(python3 -c "import json,sys; d=json.load(open('${TARGET}/train_data/cell_filters/cell_filters.json')); print(len(d.get('active_filters',[])))" 2>/dev/null || echo "?")
    _hitl_p=$(find "${TARGET}/train_data/cell_filters/polygons" -name '*.png' 2>/dev/null | wc -l)
    log_info "  HitL-Daten gefunden: ${_hitl_n} Filter, ${_hitl_p} Polygon-PNGs — bleiben erhalten"
else
    log_info "  ${TARGET}/train_data/cell_filters/         (HitL-Filter — wird beim ersten Polygon initialisiert)"
    log_info "  ${TARGET}/train_data/cell_filters/polygons/ (Polygon-PNGs)"
fi

# Bei full-Modus: Journal + Evaluation-Logs leeren (sonst sieht /logs nach
# Neuinstallation noch alle Logs der alten Installation)
if [[ "$MODE" == "full" ]]; then
    log_info "Leere systemd Journal-Logs für Wetterprojekt-Services..."
    sudo journalctl --rotate 2>/dev/null || true
    for _unit in wetterprojekt wetterprojekt-scheduler wetterprojekt-admin; do
        sudo journalctl --vacuum-time=1s --unit="$_unit" 2>/dev/null || true
    done
    # Globaler Vacuum als Fallback (ältere systemd-Versionen)
    sudo journalctl --vacuum-size=1K 2>/dev/null || true
    log_info "Journal geleert."

    _eval_dir="$TARGET/train_data/evaluation"
    if [[ -d "$_eval_dir" ]]; then
        log_info "Leere Evaluation-Logs in $_eval_dir ..."
        rm -f \
            "$_eval_dir/api_health.jsonl" \
            "$_eval_dir/api_call_counts.jsonl" \
            "$_eval_dir/cleanup_log.jsonl" \
            "$_eval_dir/cells_log.jsonl"
        # KI-Analyse-Vorschläge (ai_suggestions/) ebenfalls leeren
        if [[ -d "$_eval_dir/ai_suggestions" ]]; then
            rm -f "$_eval_dir/ai_suggestions"/*.json 2>/dev/null || true
            log_info "ai_suggestions geleert."
        fi
        log_info "Evaluation-Logs geleert."
    fi
fi

echo "[INSTALL] Modus: $MODE | no-hailo: $NO_HAILO | no-node: $NO_NODE"

# ==============================================================================
# PHASE 4 — System-Dependencies (apt)
# ==============================================================================
CURRENT_PHASE="Phase 4 — System-Dependencies"
log_step "Phase 4 — System-Dependencies"

if [[ "$SYSTEM_DEPS_ENABLED" == true && ( "$MODE" == "full" || "${UPDATE_DEPS:-false}" == "true" ) ]]; then
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
        nginx                          # Reverse-Proxy für Flask-API + React-Frontend
        apache2-utils                  # htpasswd für nginx Basic-Auth
        ca-certificates                # TLS-Root-Zertifikate aktuell halten
        openssl                        # SSL-Bibliothek
        ntp                            # Zeitsynchronisation (verhindert TLS-Fehler)
    )

    log_info "Installiere APT-Pakete: ${APT_PKGS[*]}"
    sudo apt-get install -y "${APT_PKGS[@]}" 2>&1 | grep -E "^(Inst|Err)" || true
    log_info "APT-Pakete installiert."

    # Zeitsync erzwingen — Bookworm nutzt systemd-timesyncd statt ntpdate
    log_info "Synchronisiere Systemzeit..."
    sudo timedatectl set-ntp true 2>/dev/null || true
    for _i in 1 2 3 4 5; do
        _sync=$(timedatectl show --property=NTPSynchronized --value 2>/dev/null || echo "no")
        if [[ "$_sync" == "yes" ]]; then break; fi
        sleep 1
    done
    _sync_status=$(timedatectl show --property=NTPSynchronized --value 2>/dev/null || echo "unbekannt")
    if [[ "$_sync_status" == "yes" ]]; then
        log_info "Systemzeit synchronisiert: $(date)"
    else
        log_warn "NTP-Sync ausstehend (läuft im Hintergrund) — Systemzeit: $(date)"
    fi

    # CA-Zertifikate neu aufbauen
    log_info "Aktualisiere CA-Zertifikate..."
    sudo update-ca-certificates --fresh 2>/dev/null || true
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

# ------------------------------------------------------------------------------
# pip_bootstrap: ersetzt veraltetes pip-Bundle im venv via get-pip.py
# ------------------------------------------------------------------------------
_PIP_BOOTSTRAPPED=false
pip_bootstrap() {
    if [[ "$_PIP_BOOTSTRAPPED" == true ]]; then return 0; fi
    log_warn "Versuche pip-Bootstrap via get-pip.py..."
    local GET_PIP_TMP="$TARGET/get-pip.py"
    if curl -fsSL --retry 3 --retry-delay 2 \
            --cacert /etc/ssl/certs/ca-certificates.crt \
            "https://bootstrap.pypa.io/get-pip.py" -o "$GET_PIP_TMP" 2>/dev/null; then
        log_info "get-pip.py heruntergeladen (mit CA-Verify)."
    else
        log_warn "curl mit SSL fehlgeschlagen — versuche ohne Zertifikatsprüfung..."
        curl -fsSL --retry 3 --insecure \
            "https://bootstrap.pypa.io/get-pip.py" -o "$GET_PIP_TMP" || {
            log_error "get-pip.py Download fehlgeschlagen."
            return 1
        }
    fi
    "$VENV/bin/python3" "$GET_PIP_TMP" --no-cache-dir \
        --trusted-host pypi.org \
        --trusted-host pypi.python.org \
        --trusted-host files.pythonhosted.org \
        2>&1 | tail -3
    rm -f "$GET_PIP_TMP"
    _PIP_BOOTSTRAPPED=true
    log_info "pip-Bootstrap abgeschlossen."
}

# ------------------------------------------------------------------------------
# pip_install_safe: 3-stufiger Fallback
#   Stufe 1: normaler Aufruf
#   Stufe 2: --trusted-host (SSL-Verify für PyPI-Endpunkte deaktiviert)
#   Stufe 3: get-pip.py Bootstrap + Stufe 2 wiederholen
# ------------------------------------------------------------------------------
pip_install_safe() {
    local ARGS=("$@")

    log_info "pip install (Stufe 1 — normal): ${ARGS[*]}"
    if "$VENV/bin/pip" install --no-cache-dir "${ARGS[@]}" 2>&1 | tail -5; then
        return 0
    fi

    log_warn "Stufe 1 fehlgeschlagen — versuche mit --trusted-host..."
    if "$VENV/bin/pip" install --no-cache-dir \
            --trusted-host pypi.org \
            --trusted-host pypi.python.org \
            --trusted-host files.pythonhosted.org \
            "${ARGS[@]}" 2>&1 | tail -5; then
        log_warn "Installation mit --trusted-host erfolgreich (SSL-Bypass aktiv)."
        return 0
    fi

    log_warn "Stufe 2 fehlgeschlagen — Bootstrap-Versuch..."
    if pip_bootstrap; then
        if "$VENV/bin/pip" install --no-cache-dir \
                --trusted-host pypi.org \
                --trusted-host pypi.python.org \
                --trusted-host files.pythonhosted.org \
                "${ARGS[@]}" 2>&1 | tail -5; then
            log_warn "Installation nach Bootstrap erfolgreich."
            return 0
        fi
    fi

    return 1
}

# --- pip / wheel / setuptools aktualisieren -----------------------------------
log_info "Aktualisiere pip, wheel, setuptools im venv..."
if ! pip_install_safe --upgrade pip wheel setuptools; then
    log_warn "pip-Upgrade fehlgeschlagen — fahre mit vorhandener Version fort."
    note_manual "source $VENV/bin/activate && pip install --upgrade pip wheel setuptools --trusted-host pypi.org --trusted-host files.pythonhosted.org"
    note_manual "Zeitsync prüfen: sudo timedatectl set-ntp true && date"
fi

# --- piwheels (Pi-spezifische Wheels) -----------------------------------------
PIWHEELS_EXTRA=""
if [[ "$IS_PI" == "true" ]]; then
    PIWHEELS_EXTRA="--extra-index-url https://www.piwheels.org/simple"
    log_info "piwheels als zusätzliche Index-Quelle aktiviert."
fi

# --- requirements.txt ---------------------------------------------------------
log_info "Installiere requirements.txt..."
# shellcheck disable=SC2086
if pip_install_safe -r "$TARGET/requirements.txt" $PIWHEELS_EXTRA; then
    log_info "pip-Pakete installiert."
    echo ""
    echo "[INFO] DEM-Höhendaten (Copernicus 30m) werden beim ersten Start"
    echo "       automatisch geladen (8 Kacheln × ~180 MB ≈ 1.4 GB)."
    echo "       Benötigter freier Speicher: min. 2 GB."
    echo "       Download läuft im Hintergrund-Thread — blockiert den Loop nicht."
    echo ""
    # requirements.lock: exakter Installationszustand für Reproduzierbarkeit
    log_info "Erzeuge requirements.lock (pip freeze)..."
    "$VENV/bin/pip" freeze > "$TARGET/requirements.lock" 2>/dev/null         && check_ok "requirements.lock erstellt: $(wc -l < "$TARGET/requirements.lock") Pakete"         || log_warn "requirements.lock konnte nicht erstellt werden (nicht kritisch)"
else
    log_warn "pip install hatte Fehler — bitte manuell prüfen:"
    note_manual "cd $TARGET && source venv/bin/activate && pip install -r requirements.txt --trusted-host pypi.org --trusted-host files.pythonhosted.org"
    note_manual "Zeitsync: sudo timedatectl set-ntp true && sudo ntpdate -u pool.ntp.org"
fi

# ==============================================================================
# PHASE 6 — Verzeichnisstruktur anlegen + .env prüfen
# ==============================================================================
CURRENT_PHASE="Phase 6 — Verzeichnisstruktur"
log_step "Phase 6 — Verzeichnisstruktur und .env"

DIRS=(
    train_data/radar
    train_data/objects
    train_data/weather
    train_data/wind
    train_data/cape
    train_data/dataset
    train_data/models
    train_data/ir
    train_data/ir_cells
    train_data/lightning
    train_data/evaluation
    train_data/cloud
    train_data/arome
    train_data/api_cache
    train_data/dem
    data/radar
    data
    logs
)
for d in "${DIRS[@]}"; do
    mkdir -p "$TARGET/$d"
done
log_info "Verzeichnisstruktur erstellt."

INITIAL_MODEL_SOURCE="$TARGET/weather_lstm_model.keras"
INITIAL_MODEL_TARGET="$TARGET/train_data/models/current/weather_lstm.keras"
if [[ -f "$INITIAL_MODEL_SOURCE" ]]; then
    # Bootstrap: ein initiales Versionsverzeichnis und current-Symlink anlegen
    BOOTSTRAP_VERSION="v_bootstrap"
    BOOTSTRAP_DIR="$TARGET/train_data/models/$BOOTSTRAP_VERSION"
    mkdir -p "$BOOTSTRAP_DIR"
    if [[ ! -f "$INITIAL_MODEL_TARGET" ]]; then
        cp "$INITIAL_MODEL_SOURCE" "$BOOTSTRAP_DIR/weather_lstm.keras"
        log_info "Initialmodell kopiert: $BOOTSTRAP_DIR/weather_lstm.keras"
    fi
    # current als Symlink auf Bootstrap setzen (falls noch kein Symlink existiert)
    CURRENT_LINK="$TARGET/train_data/models/current"
    if [[ ! -L "$CURRENT_LINK" ]]; then
        ln -sfn "$BOOTSTRAP_VERSION" "$CURRENT_LINK"
        log_info "Symlink gesetzt: $CURRENT_LINK → $BOOTSTRAP_VERSION"
    fi
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
# WetterExtended — Umgebungsvariablen
# WICHTIG: .env NIEMALS committen (steht in .gitignore)

# ── FTP-Upload ────────────────────────────────────────────────
FTP_SERVER=
FTP_USER=
FTP_PASS=
FTP_PATH=/wetterAI/

# ── Blitzortung.org (Teilnehmer-Login) ────────────────────────
# Leer lassen = Blitzdaten deaktiviert
BLITZ_USERNAME=
BLITZ_PASSWORD=

# ── Twilio SMS-Warnungen ──────────────────────────────────────
# Leer lassen = SMS-Warnungen deaktiviert
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_FROM=
TWILIO_TO=

# ── Anthropic API (KI-Analyse) ───────────────────────────────
# Leer lassen = KI-Analyse deaktiviert
ANTHROPIC_API_KEY=

# ── GitHub-Token (privates Repo) ─────────────────────────────
GITHUB_TOKEN=

# ── Debug-Modus ───────────────────────────────────────────────
WETTER_DEBUG=0
ENVTEMPLATE
        log_warn ".env angelegt — Credentials eintragen:"
        note_manual "nano $ENV_FILE  # FTP, BLITZ, TWILIO, ANTHROPIC_API_KEY, GITHUB_TOKEN setzen"
    fi
else
    # FTP-Credentials prüfen
    FTP_OK=true
    for var in FTP_SERVER FTP_USER FTP_PASS; do
        val=$(grep "^${var}=" "$ENV_FILE" | cut -d= -f2 | tr -d ' ' || true)
        [[ -z "$val" ]] && { FTP_OK=false; break; }
    done
    if [[ "$FTP_OK" == "true" ]]; then
        check_ok ".env: FTP-Credentials konfiguriert"
    else
        check_warn ".env: FTP-Credentials unvollständig"
        note_manual "nano $ENV_FILE  # FTP_SERVER, FTP_USER, FTP_PASS prüfen"
    fi

    # ADMIN_API_TOKEN generieren (einmalig, bei Upgrade beibehalten)
    EXISTING_ADMIN_TOKEN=$(grep "^ADMIN_API_TOKEN=" "$ENV_FILE" 2>/dev/null | cut -d= -f2 | tr -d ' ' || true)
    if [[ -z "$EXISTING_ADMIN_TOKEN" ]]; then
        NEW_ADMIN_TOKEN=$(openssl rand -hex 32)
        echo "ADMIN_API_TOKEN=${NEW_ADMIN_TOKEN}" >> "$ENV_FILE"
        check_ok ".env: ADMIN_API_TOKEN generiert ($(echo "${NEW_ADMIN_TOKEN}" | cut -c1-8)...)"
    else
        check_ok ".env: ADMIN_API_TOKEN vorhanden"
    fi

    # P31: ADMIN_REQUIRE_TOKEN=1 — fail-closed im Produktivbetrieb.
    # Wenn ADMIN_API_TOKEN fehlt, startet die App nicht (SystemExit).
    # Zum Deaktivieren: ADMIN_REQUIRE_TOKEN=0 in .env setzen.
    if ! grep -q "^ADMIN_REQUIRE_TOKEN=" "$ENV_FILE" 2>/dev/null; then
        echo "ADMIN_REQUIRE_TOKEN=1" >> "$ENV_FILE"
        check_ok ".env: ADMIN_REQUIRE_TOKEN=1 gesetzt (fail-closed Standard)"
    else
        check_ok ".env: ADMIN_REQUIRE_TOKEN vorhanden ($(grep "^ADMIN_REQUIRE_TOKEN=" "$ENV_FILE" | cut -d= -f2 || true))"
    fi

    # Blitzortung-Credentials prüfen
    BLITZ_USER_VAL=$(grep "^BLITZ_USERNAME=" "$ENV_FILE" 2>/dev/null | cut -d= -f2 | tr -d ' ' || true)
    BLITZ_PASS_VAL=$(grep "^BLITZ_PASSWORD=" "$ENV_FILE" 2>/dev/null | cut -d= -f2 | tr -d ' ' || true)
    if [[ -n "$BLITZ_USER_VAL" && -n "$BLITZ_PASS_VAL" ]]; then
        check_ok ".env: Blitzortung-Credentials konfiguriert"
    else
        check_warn ".env: BLITZ_USERNAME / BLITZ_PASSWORD nicht gesetzt — Blitzdaten deaktiviert"
        note_manual "nano $ENV_FILE  # BLITZ_USERNAME, BLITZ_PASSWORD setzen (Blitzortung-Login)"
    fi

    # Anthropic API Key prüfen
    ANTHROPIC_VAL=$(grep "^ANTHROPIC_API_KEY=" "$ENV_FILE" 2>/dev/null | cut -d= -f2 | tr -d ' ' || true)
    if [[ -n "$ANTHROPIC_VAL" ]]; then
        check_ok ".env: ANTHROPIC_API_KEY konfiguriert (KI-Analyse verfügbar)"
    else
        check_warn ".env: ANTHROPIC_API_KEY nicht gesetzt — KI-Analyse deaktiviert"
        note_manual "nano $ENV_FILE  # ANTHROPIC_API_KEY setzen (optional, für KI-Analyse)"
    fi

    # GitHub Token prüfen (privates Repo)
    GITHUB_TOKEN_VAL=$(grep "^GITHUB_TOKEN=" "$ENV_FILE" 2>/dev/null | cut -d= -f2 | tr -d ' ' || true)
    if [[ -n "$GITHUB_TOKEN_VAL" ]]; then
        check_ok ".env: GITHUB_TOKEN gesetzt (KI-Analyse kann Quellcode vom privaten Repo laden)"
    else
        check_warn ".env: GITHUB_TOKEN nicht gesetzt — KI-Analyse lädt keinen Quellcode"
        note_manual "nano $ENV_FILE  # GITHUB_TOKEN setzen (GitHub PAT, repo:read Berechtigung)"
    fi
fi

# LOCAL_TRAINING Flag in runtime_overrides.json schreiben (nur wenn --no-training)
if [[ "$LOCAL_TRAINING_FLAG" == "false" ]]; then
    log_info "Setze LOCAL_TRAINING=False in runtime_overrides.json ..."
    "$VENV/bin/python3" - <<PYEOF
import json, os
path = "$TARGET/train_data/runtime_overrides.json"
os.makedirs(os.path.dirname(path), exist_ok=True)
data = {}
if os.path.exists(path):
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception:
        data = {}
data["LOCAL_TRAINING"] = False
with open(path, "w") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
print("[INSTALL] LOCAL_TRAINING=False in runtime_overrides.json gesetzt.")
PYEOF
    check_ok "LOCAL_TRAINING=False gesetzt (Phase B: Training auf Linux-Rechner)"
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

    # hailo-all ist ab Raspberry Pi OS Bookworm (Dez. 2024) im Standard-Repo enthalten.
    # Kein zusätzliches APT-Repository erforderlich.
    # Quelle: https://www.raspberrypi.com/documentation/accessories/ai-kit.html
    if [[ "$APT_UPDATED" == "false" ]]; then
        sudo apt-get update -qq && APT_UPDATED=true
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
    # hailo-platform ist NICHT auf PyPI/piwheels — kommt als System-Paket mit hailo-all.
    # Strategie: 1) Import-Test  2) pip-Versuch  3) .pth-Fallback auf System-Paket
    HAILO_BOUND=false

    if "$VENV/bin/python3" -c "import hailo_platform" 2>/dev/null; then
        check_ok "hailo-platform: bereits im venv importierbar"
        HAILO_BOUND=true
    fi

    if [[ "$HAILO_BOUND" == false ]]; then
        log_info "Versuche hailo-platform via pip..."
        if "$VENV/bin/pip" install hailo-platform -q 2>/dev/null; then
            check_ok "hailo-platform: via pip installiert"
            HAILO_BOUND=true
        fi
    fi

    if [[ "$HAILO_BOUND" == false ]]; then
        log_info "pip fehlgeschlagen — suche System-hailo_platform..."
        HAILO_SYS_PATH=""
        for candidate in \
            /usr/lib/python3/dist-packages \
            /usr/local/lib/python3.11/dist-packages \
            /usr/local/lib/python3.10/dist-packages \
            /usr/lib/python3.11/dist-packages \
            /usr/lib/python3.10/dist-packages; do
            if [[ -d "${candidate}/hailo_platform" ]]; then
                HAILO_SYS_PATH="$candidate"
                break
            fi
        done
        if [[ -z "$HAILO_SYS_PATH" ]]; then
            HAILO_SYS_PATH=$(python3 -c "
import sys, os
for p in sys.path:
    if os.path.isdir(os.path.join(p, 'hailo_platform')):
        print(p); break
" 2>/dev/null || true)
        fi
        if [[ -n "$HAILO_SYS_PATH" ]]; then
            VENV_SITE=$("$VENV/bin/python3" -c "import site; print(site.getsitepackages()[0])")
            echo "$HAILO_SYS_PATH" > "$VENV_SITE/hailo_system.pth"
            if "$VENV/bin/python3" -c "import hailo_platform" 2>/dev/null; then
                check_ok "hailo-platform: via .pth eingebunden ($HAILO_SYS_PATH)"
                HAILO_BOUND=true
            else
                check_warn "hailo-platform: .pth gesetzt, Import fehlgeschlagen"
                note_manual "$VENV/bin/python3 -c 'import hailo_platform'"
            fi
        else
            log_warn "hailo_platform System-Paket nicht gefunden."
            note_manual "Nach Reboot: source $VENV/bin/activate && python3 -c 'import hailo_platform'"
        fi
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

        # npm ci wenn package-lock.json vorhanden (reproduzierbar), sonst npm install
        _NPM_CMD="install"
        [[ -f "$TARGET/frontend/package-lock.json" ]] && _NPM_CMD="ci"
        log_info "npm ${_NPM_CMD} (package-lock.json $([ "$_NPM_CMD" = ci ] && echo 'vorhanden → ci' || echo 'fehlt → install'))..."
        # package-lock.json generieren wenn nicht vorhanden (P32: reproduzierbarer Build)
        if [[ ! -f "$TARGET/frontend/package-lock.json" ]]; then
            log_info "package-lock.json fehlt — einmalig generieren mit npm install --package-lock-only..."
            npm install --package-lock-only --no-audit --no-fund 2>&1 | tail -3 || true
            if [[ -f "$TARGET/frontend/package-lock.json" ]]; then
                check_ok "package-lock.json generiert — bitte in Git committen:"
                log_info "  cd $TARGET/frontend && git add package-lock.json && git commit -m 'add package-lock.json'"
            else
                log_warn "package-lock.json konnte nicht generiert werden — npm install wird verwendet"
            fi
        fi
        if npm ${_NPM_CMD} --no-audit --no-fund 2>&1 | tail -3; then
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
# PHASE 7d — nginx: Reverse-Proxy für Flask-API + React-SPA
# ==============================================================================
CURRENT_PHASE="PHASE 7d — nginx"
log_step "Phase 7d — nginx Reverse-Proxy"

NGINX_SITE_CONF="/etc/nginx/sites-available/wetterprojekt"
NGINX_SITE_ENABLED="/etc/nginx/sites-enabled/wetterprojekt"
NGINX_DEFAULT_ENABLED="/etc/nginx/sites-enabled/default"
FRONTEND_DIST="$TARGET/frontend/dist"

if command -v nginx &>/dev/null; then

    # Basic-Auth: Passwort generieren (einmalig, bei Upgrade beibehalten)
    ADMIN_PASS_FILE="$TARGET/.admin_password"
    if [[ ! -f "$ADMIN_PASS_FILE" ]]; then
        ADMIN_PASS=$(openssl rand -base64 16 | tr -d '/+=\n' | head -c 16)
        echo "$ADMIN_PASS" | sudo htpasswd -ic /etc/nginx/.htpasswd admin
        echo "$ADMIN_PASS" > "$ADMIN_PASS_FILE"
        chmod 600 "$ADMIN_PASS_FILE"
        check_ok "nginx Basic-Auth: Passwort generiert → $ADMIN_PASS_FILE"
        echo -e "${YELLOW}  Admin-Passwort: ${ADMIN_PASS}${NC}"
        echo -e "${YELLOW}  (auch gespeichert in: $ADMIN_PASS_FILE)${NC}"
    else
        log_info "nginx Basic-Auth: $ADMIN_PASS_FILE vorhanden — Passwort unverändert."
        # htpasswd wiederherstellen falls gelöscht (z. B. nach OS-Neuinstallation)
        if [[ ! -f /etc/nginx/.htpasswd ]]; then
            EXISTING_PASS=$(cat "$ADMIN_PASS_FILE" 2>/dev/null || true)
            if [[ -n "$EXISTING_PASS" ]]; then
                echo "$EXISTING_PASS" | sudo htpasswd -ic /etc/nginx/.htpasswd admin
                check_ok "nginx Basic-Auth: .htpasswd aus $ADMIN_PASS_FILE wiederhergestellt."
            else
                check_warn "nginx Basic-Auth: .admin_password leer — Basic-Auth deaktiviert."
            fi
        fi
    fi

    log_info "Generiere nginx-Konfiguration: $NGINX_SITE_CONF"
    sudo tee "$NGINX_SITE_CONF" > /dev/null <<NGINXCONF
# WetterExtended — nginx Reverse-Proxy
# Generiert von install.sh am $(date '+%Y-%m-%d %H:%M:%S')

server {
    listen 80;
    listen [::]:80;
    server_name _;

    auth_basic           "WetterExtended Admin";
    auth_basic_user_file /etc/nginx/.htpasswd;

    root ${FRONTEND_DIST};
    index index.html;

    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml image/svg+xml;
    gzip_min_length 1024;

    location / {
        try_files \$uri \$uri/ /index.html;
        add_header Cache-Control "no-cache";
    }

    # Vollbild-Karte: ohne Authentifizierung erreichbar
    # Regex-Match deckt /karte, /karte/ und /karte/* ab (Trailing-Slash-Fix)
    location ~ ^/karte(/.*)?$ {
        auth_basic off;
        try_files \$uri /index.html;
        add_header Cache-Control "no-cache";
    }

    # SPA-Einstiegsdatei ohne Auth.
    # try_files $uri /index.html im /karte-Block macht einen internen nginx-Redirect
    # auf /index.html. Ohne diesen Block landet der Redirect im / Block (mit auth_basic)
    # und verursacht 401 — obwohl /karte auth_basic off hat.
    location = /index.html {
        auth_basic off;
        add_header Cache-Control "no-cache";
    }

    # Favicon ohne Auth (404 statt 401 wenn kein favicon vorhanden)
    location = /favicon.ico {
        auth_basic off;
        expires 1y;
        add_header Cache-Control "public, immutable";
        try_files \$uri =404;
    }

    # Leaflet-Assets: ohne Auth (werden von /karte geladen)
    location /assets/ {
        auth_basic off;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # API-Endpunkte fuer oeffentliche Karte (nur lesend, kein POST)
    # Fix #9: lightning + risk_grid öffentlich freigeben (öffentliche /karte-Ansicht)
    location ~ ^/api/(objects|forecast|locations|horizons|health|radar_image|radar_bounds|radar_timing|radar_frames|lightning|risk_grid)$ {
        auth_basic off;
        proxy_pass         http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header   Host              \$host;
        proxy_set_header   X-Real-IP         \$remote_addr;
        proxy_set_header   X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_read_timeout 30s;
    }

    location /api/ {
        proxy_pass         http://127.0.0.1:5000/api/;
        proxy_http_version 1.1;
        proxy_set_header   Host              \$host;
        proxy_set_header   X-Real-IP         \$remote_addr;
        proxy_set_header   X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
        proxy_connect_timeout 10s;
    }

    # Finding #4 Fix: /export/ ist keine Flask-Route.
    # Redirect auf kanonische API-Route /api/export/forecast.kmz
    location = /export/forecast.kmz {
        return 301 /api/export/forecast.kmz;
    }
    location /export/ {
        return 301 /api/export/forecast.kmz;
    }

    location /plots/ {
        alias ${TARGET}/plots/;
        expires 5m;
        add_header Cache-Control "public";
    }

    location /nginx_status {
        stub_status;
        allow 127.0.0.1;
        deny all;
    }
}
NGINXCONF

    if [[ -f "$NGINX_DEFAULT_ENABLED" ]]; then
        sudo rm -f "$NGINX_DEFAULT_ENABLED"
        log_info "nginx default-Site deaktiviert."
    fi

    if [[ ! -L "$NGINX_SITE_ENABLED" ]]; then
        sudo ln -sfn "$NGINX_SITE_CONF" "$NGINX_SITE_ENABLED"
        log_info "nginx Site aktiviert: $NGINX_SITE_ENABLED"
    fi

    if sudo nginx -t 2>/dev/null; then
        check_ok "nginx Konfiguration: syntaktisch korrekt"
        if systemctl is-active --quiet nginx 2>/dev/null; then
            sudo systemctl reload nginx
            check_ok "nginx: Konfiguration neu geladen"
        else
            sudo systemctl enable nginx --now
            if systemctl is-active --quiet nginx; then
                check_ok "nginx: gestartet und aktiviert"
            else
                check_warn "nginx konnte nicht gestartet werden"
                note_manual "sudo systemctl status nginx"
            fi
        fi
    else
        check_warn "nginx Konfigurationstest fehlgeschlagen"
        note_manual "sudo nginx -t && sudo systemctl reload nginx"
    fi

    if [[ ! -f "$FRONTEND_DIST/index.html" ]]; then
        check_warn "Frontend-Dist fehlt — wird nach npm run build verfügbar."
        note_manual "cd $TARGET/frontend && npm run build && sudo systemctl reload nginx"
    else
        check_ok "nginx: Frontend-Dist vorhanden ($FRONTEND_DIST/index.html)"
    fi

    PI_IP=$(hostname -I | awk '{print $1}')
    log_info "Adminpanel erreichbar unter: http://${PI_IP}/"

    chmod o+x "$HOME"
    check_ok "Heimverzeichnis traversierbar für nginx (o+x)"

else
    check_warn "nginx nicht installiert — Phase übersprungen."
    note_manual "sudo apt install nginx && sudo systemctl enable --now nginx"
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
    for svc_file in wetterprojekt.service wetterprojekt-scheduler.service wetterprojekt-admin.service; do
        generated="$TARGET/.generated-$svc_file"
        if [[ -f "$generated" ]]; then
            sudo cp "$generated" "/etc/systemd/system/$svc_file"
        else
            check_warn "Service-Datei nicht gefunden: $svc_file"
        fi
    done

    # Watchdog-Patch: Type=notify + WatchdogSec=60 in alle generierten Service-Files
    # (systemd startet bei ausbleibendem Watchdog-Ping automatisch neu)
    for _svc_gen in "$TARGET"/.generated-wetterprojekt*.service; do
        [[ -f "$_svc_gen" ]] || continue
        # Type=simple → Type=notify (oder hinzufügen wenn kein Type= vorhanden)
        if grep -q "^Type=simple" "$_svc_gen"; then
            sed -i 's/^Type=simple/Type=notify/' "$_svc_gen"
            log_info "Watchdog: Type=notify gesetzt in $(basename "$_svc_gen")"
        elif ! grep -q "^Type=" "$_svc_gen"; then
            sed -i '/^\[Service\]/a Type=notify' "$_svc_gen"
            log_info "Watchdog: Type=notify eingefügt in $(basename "$_svc_gen")"
        fi
        # WatchdogSec und NotifyAccess hinzufügen wenn noch nicht vorhanden
        if ! grep -q "^WatchdogSec=" "$_svc_gen"; then
            sed -i '/^Type=notify/a WatchdogSec=60\nNotifyAccess=main' "$_svc_gen"
            log_info "Watchdog: WatchdogSec=60 gesetzt in $(basename "$_svc_gen")"
        fi
        # Restart-Policy sicherstellen
        if ! grep -q "^Restart=" "$_svc_gen"; then
            sed -i '/^WatchdogSec=/a Restart=on-failure\nRestartSec=10s' "$_svc_gen"
        fi
    done
    # Gepatchte Files in systemd kopieren
    for svc_file in wetterprojekt.service wetterprojekt-scheduler.service wetterprojekt-admin.service; do
        generated="$TARGET/.generated-$svc_file"
        [[ -f "$generated" ]] && sudo cp "$generated" "/etc/systemd/system/$svc_file"
    done

    sudo systemctl daemon-reload

    # journald-Limit: SD-Karte vor unkontrolliertem Log-Wachstum schützen
    _JOURNALD_DROP_IN_DIR="/etc/systemd/journald.conf.d"
    _JOURNALD_DROP_IN="$_JOURNALD_DROP_IN_DIR/wetterprojekt.conf"
    if [[ ! -f "$_JOURNALD_DROP_IN" ]]; then
        sudo mkdir -p "$_JOURNALD_DROP_IN_DIR"
        sudo tee "$_JOURNALD_DROP_IN" > /dev/null << 'JOURNALDCONF'
# WetterExtended — journald-Limit
# Generiert von install.sh — schützt SD-Karte vor Journal-Überwuchs.
[Journal]
SystemMaxUse=200M
SystemKeepFree=500M
MaxRetentionSec=14day
JOURNALDCONF
        sudo systemctl restart systemd-journald 2>/dev/null || true
        check_ok "journald-Limit gesetzt: max 200 MB, min 500 MB frei, max 14 Tage"
    else
        log_info "journald-Drop-In vorhanden: $_JOURNALD_DROP_IN (unverändert)"
    fi

    for svc_file in wetterprojekt.service wetterprojekt-scheduler.service wetterprojekt-admin.service; do
        if [[ -f "/etc/systemd/system/$svc_file" ]]; then
            svc_name="${svc_file}"
            # StartLimit-Counter zurücksetzen (verhindert "start request repeated too quickly")
            sudo systemctl reset-failed "$svc_name" 2>/dev/null || true
            sudo systemctl enable "$svc_name" || true
            sudo systemctl start "$svc_name" || true
            sleep 3  # Startzeit abwarten
            systemctl is-active --quiet "$svc_name" \
                && check_ok "Service aktiv: $svc_name" \
                || check_warn "Service konnte nicht gestartet werden: $svc_name"
        fi
    done
else
    log_warn "Services werden nicht aktiviert (--enable-services nicht gesetzt)."
    # Im upgrade-Modus: vorher gestoppte Services automatisch neu starten
    if [[ "${_RESTART_AFTER_UPGRADE:-false}" == "true" && ${#_RUNNING_SERVICES[@]} -gt 0 ]]; then
        log_info "Starte Services nach Upgrade neu..."
        sudo systemctl daemon-reload 2>/dev/null || true
        for _svc in "${_RUNNING_SERVICES[@]}"; do
            sudo systemctl reset-failed "$_svc" 2>/dev/null || true
            if sudo systemctl start "$_svc" 2>/dev/null; then
                sleep 2
                systemctl is-active --quiet "$_svc" \
                    && check_ok "$_svc neu gestartet" \
                    || check_warn "$_svc gestartet aber nicht aktiv — prüfen: journalctl -u $_svc -n 20"
            else
                log_warn "$_svc konnte nicht gestartet werden"
                note_manual "sudo systemctl start $_svc && journalctl -u $_svc -n 30"
            fi
        done
    else
        note_manual "sudo systemctl daemon-reload && sudo systemctl enable --now wetterprojekt wetterprojekt-scheduler wetterprojekt-admin"
    fi
fi

# ==============================================================================
# PHASE 8 — Abschluss-Report
# ==============================================================================
CURRENT_PHASE="Phase 8 — Abschluss-Report"
log_step "Phase 8 — Abschluss-Report"

if [[ -d "$TARGET/.git" ]]; then
    SOURCE_INFO="$(cd "$TARGET" && git rev-parse --abbrev-ref HEAD 2>/dev/null) @ $(cd "$TARGET" && git rev-parse --short HEAD 2>/dev/null)"
else
    SOURCE_INFO="lokal/ZIP (ohne Git)"
fi

FRONTEND_STATUS="fehlt ❌"
[[ -f "$TARGET/frontend/dist/index.html" ]] && FRONTEND_STATUS="gebaut ✅"

ENV_STATUS="fehlt"
[[ -f "$TARGET/.env" ]] && ENV_STATUS="vorhanden"

PYTHON_STATUS="nicht verfügbar"
[[ -x "$VENV/bin/python3" ]] && PYTHON_STATUS="$("$VENV/bin/python3" --version 2>&1)"

NODE_STATUS="$(node --version 2>/dev/null || echo 'nicht installiert')"
HAILO_STATUS="$(command -v hailortcli &>/dev/null && hailortcli --version 2>/dev/null | head -1 || echo 'nicht installiert')"
NGINX_STATUS="$(systemctl is-active nginx 2>/dev/null || echo 'nicht aktiv')"

echo ""
echo "════════════════════════════════════════════"
printf "  ${GREEN}%-20s${NC} %s\n" "Modus:"       "$MODE"
printf "  ${GREEN}%-20s${NC} %s\n" "Source:"      "$SOURCE_INFO"
printf "  ${GREEN}%-20s${NC} %s\n" "Repo:"        "$REPO"
printf "  ${GREEN}%-20s${NC} %s\n" "Target:"      "$TARGET"
printf "  ${GREEN}%-20s${NC} %s\n" "Python:"      "$PYTHON_STATUS"
printf "  ${GREEN}%-20s${NC} %s\n" "Node.js:"     "$NODE_STATUS"
printf "  ${GREEN}%-20s${NC} %s\n" "Frontend:"    "$FRONTEND_STATUS"
printf "  ${GREEN}%-20s${NC} %s\n" "Hailo:"       "$HAILO_STATUS"
printf "  ${GREEN}%-20s${NC} %s\n" "nginx:"       "$NGINX_STATUS"
printf "  ${GREEN}%-20s${NC} %s\n" ".env:"        "$ENV_STATUS"
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
cat <<NEXTSTEPS

Nächste Schritte nach Abschluss:
  1. .env befüllen (FTP-Credentials):
       nano ${TARGET}/.env

  2. Services aktivieren (falls --enable-services nicht gesetzt war):
       sudo systemctl daemon-reload
       sudo systemctl enable --now wetterprojekt wetterprojekt-scheduler wetterprojekt-admin

  3. Erstes Training starten (nach Datensammlung ~1h):
       cd ${TARGET}
       source venv/bin/activate
       python3 dataset_builder.py && python3 model_training.py

  4. Adminpanel öffnen (nginx Port 80):
       http://<pi-ip>/
     Direktzugriff Flask (ohne nginx):
       http://<pi-ip>:5000/

  5. Logs live:
       journalctl -fu wetterprojekt
NEXTSTEPS
