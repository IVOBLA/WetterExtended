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
DEFAULT_VERSION=""   # leer = main Branch; gesetzt = Git-Tag auschecken
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


# Runtime-Overrides sind Benutzereinstellungen. Bei Upgrades von alten
# Versionen kann train_data/runtime_overrides.json noch im Git-Index verfolgt
# und lokal geändert sein. Deshalb vor Git-Operationen sichern, lokale
# Index-Konflikte für genau diese Datei neutralisieren und danach wiederherstellen.
RUNTIME_OVERRIDES_REL="train_data/runtime_overrides.json"
RUNTIME_OVERRIDES_BACKUP=""
RUNTIME_OVERRIDES_SHA_BEFORE=""
RUNTIME_OVERRIDES_SHA_AFTER=""

backup_runtime_overrides() {
    local runtime_path="$TARGET/$RUNTIME_OVERRIDES_REL"
    local backup_dir="$TARGET/train_data/install_backups"
    if [[ -f "$runtime_path" ]]; then
        mkdir -p "$backup_dir"
        chmod 700 "$backup_dir" 2>/dev/null || true
        local ts
        ts=$(date -u +%Y%m%d_%H%M%S)
        RUNTIME_OVERRIDES_BACKUP="$backup_dir/runtime_overrides_${ts}.json"
        cp -p "$runtime_path" "$RUNTIME_OVERRIDES_BACKUP"
        chmod 600 "$RUNTIME_OVERRIDES_BACKUP" 2>/dev/null || true
        RUNTIME_OVERRIDES_SHA_BEFORE=$(sha256sum "$runtime_path" | awk '{print $1}')
        log_info "runtime_overrides.json vor Source-Update persistent gesichert: $RUNTIME_OVERRIDES_BACKUP"
        log_info "runtime_overrides.json SHA256 vor Upgrade: $RUNTIME_OVERRIDES_SHA_BEFORE"
    fi

    if [[ -d "$TARGET/.git" ]]; then
        (
            cd "$TARGET"
            if git ls-files --error-unmatch "$RUNTIME_OVERRIDES_REL" >/dev/null 2>&1; then
                git checkout -- "$RUNTIME_OVERRIDES_REL" 2>/dev/null || true
            fi
        )
    fi
}

restore_runtime_overrides() {
    local runtime_path="$TARGET/$RUNTIME_OVERRIDES_REL"
    if [[ -n "$RUNTIME_OVERRIDES_BACKUP" && -f "$RUNTIME_OVERRIDES_BACKUP" ]]; then
        mkdir -p "$(dirname "$runtime_path")"
        if cp "$RUNTIME_OVERRIDES_BACKUP" "$runtime_path"; then
            chmod 600 "$runtime_path" 2>/dev/null || true
            log_info "runtime_overrides.json aus persistentem Backup wiederhergestellt."
        else
            log_error "Restore von runtime_overrides.json fehlgeschlagen. Manuell ausführen:"
            log_error "  cp '$RUNTIME_OVERRIDES_BACKUP' '$runtime_path'"
            return 1
        fi
    fi

    if [[ -d "$TARGET/.git" ]]; then
        (
            cd "$TARGET"
            if git ls-files --error-unmatch "$RUNTIME_OVERRIDES_REL" >/dev/null 2>&1; then
                git update-index --skip-worktree "$RUNTIME_OVERRIDES_REL" 2>/dev/null || true
            fi
        )
    fi
}

log_runtime_overrides_sha_after() {
    local runtime_path="$TARGET/$RUNTIME_OVERRIDES_REL"
    if [[ -f "$runtime_path" ]]; then
        RUNTIME_OVERRIDES_SHA_AFTER=$(sha256sum "$runtime_path" | awk '{print $1}')
        log_info "runtime_overrides.json SHA256 nach Upgrade: $RUNTIME_OVERRIDES_SHA_AFTER"
    fi
}

verify_runtime_overrides_preserved() {
    local runtime_path="$TARGET/$RUNTIME_OVERRIDES_REL"
    [[ -n "$RUNTIME_OVERRIDES_BACKUP" && -f "$RUNTIME_OVERRIDES_BACKUP" && -f "$runtime_path" ]] || return 0
    "$PYTHON_FOR_INIT" - "$RUNTIME_OVERRIDES_BACKUP" "$runtime_path" <<'PYVERIFY'
import json, sys
before_path, after_path = sys.argv[1:3]
with open(before_path, encoding="utf-8") as f:
    before = json.load(f)
with open(after_path, encoding="utf-8") as f:
    after = json.load(f)
if not isinstance(before, dict) or not isinstance(after, dict):
    raise SystemExit("runtime_overrides.json muss ein JSON-Objekt sein")
for key, value in before.items():
    if key not in after:
        raise SystemExit(f"Bestehender Key wurde entfernt: {key}")
    if after[key] != value:
        raise SystemExit(f"Bestehender Key wurde verändert: {key}")
locations = before.get("LOCATIONS_WATCHLIST")
if locations is not None:
    if after.get("LOCATIONS_WATCHLIST") != locations:
        raise SystemExit("LOCATIONS_WATCHLIST wurde ersetzt oder verändert")
    for idx, loc in enumerate(after["LOCATIONS_WATCHLIST"]):
        if isinstance(loc, dict):
            for field in ("email", "whatsapp"):
                if field in locations[idx] and loc.get(field) != locations[idx].get(field):
                    raise SystemExit(f"LOCATIONS_WATCHLIST[{idx}].{field} wurde entfernt oder verändert")
print("runtime_overrides preserved")
PYVERIFY
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
FORCE_DOWNLOAD=false
ENABLE_SERVICES=false
ENABLE_DEBUG_EXPORT_GIT=true
DEBUG_EXPORT_BRANCH="debug-export-latest"
DEBUG_EXPORT_TARGET_PATH="debug_exports/wetterextended_debug_latest_last24h.zip"
DEBUG_EXPORT_MAX_SOURCE_TOTAL_MB=512
DEBUG_EXPORT_MAX_ZIP_MB=90
LOCAL_TRAINING_FLAG=true          # --no-training setzt auf false (Phase B)
BRANCH="$DEFAULT_BRANCH"
GIT_TAG="$DEFAULT_VERSION"
REPO="$DEFAULT_REPO_URL"
TARGET="$DEFAULT_TARGET"
APT_UPDATED=false
SERVICE_USER="$(id -un)"

# --- Trap / Lock --------------------------------------------------------------
cleanup_lock() { rm -f "$LOCK_FILE"; }
on_error() {
    local exit_code=$?
    log_error "Fehler in Phase: ${CURRENT_PHASE} (Exit-Code: ${exit_code})"
    if [[ -n "${RUNTIME_OVERRIDES_BACKUP:-}" ]]; then
        restore_runtime_overrides || {
            log_error "Manuelle Wiederherstellung erforderlich:"
            log_error "  cp '$RUNTIME_OVERRIDES_BACKUP' '$TARGET/$RUNTIME_OVERRIDES_REL'"
        }
    fi
    [[ ${#MANUAL_STEPS[@]} -gt 0 ]] && {
        echo -e "\n${YELLOW}Manuelle Schritte die noch nötig sind:${NC}"
        for s in "${MANUAL_STEPS[@]}"; do echo "$s"; done
    }
    exit "$exit_code"
}
trap on_error ERR
trap 'on_error' INT TERM
trap cleanup_lock EXIT
[[ -e "$LOCK_FILE" ]] && { log_error "Lock-Datei existiert. Läuft bereits eine Installation?"; exit 1; }
touch "$LOCK_FILE"

# --- Usage --------------------------------------------------------------------
usage() { cat <<USAGE
Verwendung: $0 [OPTIONEN]

  --version <tag>       Git-Tag auschecken, z.B. v1.2.0
                        Kein --version = ${DEFAULT_BRANCH} Branch (Default)
  --list-versions       Alle verfügbaren Tags ausgeben und beenden
  --repo <url>          Repository-URL (Default SSH: ${DEFAULT_REPO_URL})
  --target <pfad>       Zielpfad (Default: ${DEFAULT_TARGET})
  --mode <full|upgrade> full = alles neu, upgrade = nur Source (Default: upgrade)
  --enable-services     systemd-Services aktivieren
  --no-system-deps      apt-Installationen überspringen
  --no-hailo            Hailo-8-Setup überspringen
  --no-node             Node.js/Frontend-Build überspringen
  --no-training         LOCAL_TRAINING=False setzen (Phase B: Training auf Linux-Rechner)
  --reset-ml            Nach Backup Modelle und generierte Datasets entfernen
  --reset-ml-full       Nach Backup Modelle, Datasets und alte ML-Trainingsquellen archivieren
  --no-debug-export-git
                       Automatischen GitHub-Debug-Export im separaten Branch nicht einrichten
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
RESET_ML_MODE=""
# B222: Original-Aufrufargumente sichern (für Selbst-Neustart nach Source-Update).
_ORIG_ARGV=("$@")
while [[ $# -gt 0 ]]; do
    case "$1" in
        --version)        GIT_TAG="$2"; shift 2 ;;
        --list-versions)
            log_info "Verfügbare Versionen (Tags):"
            git ls-remote --tags "$DEFAULT_REPO_URL" \
                | awk '{print $2}' \
                | grep -v '\^{}' \
                | sed 's|refs/tags/||' \
                | sort -V
            exit 0 ;;
        --repo)           REPO="$2"; shift 2 ;;
        --target)         TARGET="$2"; shift 2 ;;
        --mode)           MODE="$2"
                          [[ "$MODE" == "full" || "$MODE" == "upgrade" ]] || {
                              log_error "--mode muss 'full' oder 'upgrade' sein."; exit 1; }
                          shift 2 ;;
        --enable-services) ENABLE_SERVICES=true; shift ;;
        --no-system-deps) SYSTEM_DEPS_ENABLED=false; shift ;;
        --force)          FORCE_DOWNLOAD=true; shift ;;
        --no-hailo)       INSTALL_HAILO=false; NO_HAILO=1; shift ;;
        --no-node)        INSTALL_NODE=false; NO_NODE=1; shift ;;
        --no-training)    LOCAL_TRAINING_FLAG=false; shift ;;
        --reset-ml)       RESET_ML_MODE="models_only"; shift ;;
        --reset-ml-full)  RESET_ML_MODE="full_new_data_only"; shift ;;
        --no-debug-export-git) ENABLE_DEBUG_EXPORT_GIT=false; shift ;;
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
                          echo "  --no-debug-export-git  Automatischen GitHub-Debug-Export nicht einrichten"
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
[[ -f /proc/device-tree/model ]] && PI_MODEL=$(tr -d '\0' < /proc/device-tree/model 2>/dev/null || true)
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

# B222: Stand des eigenen Skripts VOR dem Source-Update festhalten. Aktualisiert
# das Update install.sh selbst, muss der Rest des Laufs mit dem NEUEN Skript
# erfolgen — sonst führt der laufende Bash-Prozess das alte Skript zu Ende aus.
_SELF_PATH="$TARGET/install.sh"
if [[ -f "$_SELF_PATH" ]]; then
    _SELF_HASH_BEFORE="$(sha256sum "$_SELF_PATH" | awk '{print $1}')"
else
    _SELF_HASH_BEFORE="absent"
fi

backup_runtime_overrides

if [[ "$LOCAL_INSTALL" == true ]]; then
    log_info "Lokale Installation aus: $LOCAL_SOURCE"
    if [[ "$LOCAL_SOURCE" != "$TARGET" ]]; then
        mkdir -p "$TARGET"
        rsync -a --delete \
            --exclude=/.env \
            --exclude=/users.db \
            --exclude=/train_data/runtime_overrides.json \
            --exclude=/train_data/statistics/ \
            --exclude=/train_data/dem/ \
            --exclude=/train_data/cell_filters/ \
            --exclude=/train_data/cell_lineage/ \
            --exclude=/train_data/hydro/ \
            --exclude=/data/config/hydro_station_overrides.json \
            "$LOCAL_SOURCE/" "$TARGET/"
        log_info "Quellcode nach $TARGET kopiert (geschützte Benutzerdaten ausgeschlossen)."
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

    if [[ -n "$GIT_TAG" ]]; then
        # ── Version-Modus: fixer Tag-Stand ───────────────────────────────────
        git fetch --tags origin
        if ! git ls-remote --tags origin "refs/tags/$GIT_TAG" | grep -q "$GIT_TAG"; then
            log_error "Tag '$GIT_TAG' existiert nicht im Repository."
            log_error "Verfügbare Tags: bash install.sh --list-versions"
            exit 1
        fi
        git checkout -B "release-${GIT_TAG//\//-}" "refs/tags/$GIT_TAG"
        if [[ "$MODE" == "full" ]]; then
            git reset --hard "refs/tags/$GIT_TAG"
        fi
        log_info "Repository auf Tag $GIT_TAG gesetzt: $(git rev-parse --short HEAD)"
    else
        # ── Default-Modus: main Branch ────────────────────────────────────────
        git fetch origin "$BRANCH"
        if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
            git checkout "$BRANCH"
        else
            git checkout -B "$BRANCH" "origin/$BRANCH"
        fi
        if [[ "$MODE" == "full" ]]; then
            git reset --hard "origin/$BRANCH"
            log_info "Repository auf remote Stand zurückgesetzt: $(git rev-parse --short HEAD)"
        else
            # Upgrade: zuerst sauberes Fast-Forward versuchen.
            if git pull --ff-only origin "$BRANCH"; then
                log_info "Repository aktualisiert (ff-only): $(git rev-parse --short HEAD)"
            else
                # Fast-Forward unmöglich (lokale Commits/Drift). Auf einem
                # Deployment-Pi soll der Code IMMER exakt origin/main entsprechen.
                # Uncommittete lokale Änderungen am Quellcode werden verworfen —
                # geschützte Benutzerdaten (.env, runtime_overrides.json,
                # train_data/) sind nicht Teil des Git-Trees und bleiben unberührt.
                log_warn "Fast-Forward nicht möglich — erzwinge Sync auf origin/$BRANCH."
                log_warn "Lokale, nicht gepushte Quellcode-Änderungen werden verworfen."
                git reset --hard "origin/$BRANCH"
                log_info "Repository hart auf origin/$BRANCH gesetzt: $(git rev-parse --short HEAD)"
            fi
        fi
    fi
else
    if [[ "$REPO" == *"<user>"* ]]; then
        log_error "Placeholder-URL erkannt: $REPO"
        log_error "Bitte --repo <echte-url> angeben oder --local verwenden."
        exit 1
    fi

    github_ssh_preflight
    _GIT_REF="${GIT_TAG:-$BRANCH}"
    git clone --branch "$_GIT_REF" "$REPO" "$TARGET"
    cd "$TARGET"
    log_info "Repository geklont ($_GIT_REF): $(git rev-parse --short HEAD)"
fi

# B222: Hat sich install.sh durch das Source-Update geändert, mit dem NEUEN
# Skript neu starten (re-exec). Doppelt abgesichert: Hash-Vergleich verhindert
# unnötigen Neustart, Umgebungsflag verhindert Endlosschleife.
if [[ -f "$_SELF_PATH" ]]; then
    _SELF_HASH_AFTER="$(sha256sum "$_SELF_PATH" | awk '{print $1}')"
else
    _SELF_HASH_AFTER="absent"
fi
if [[ "${WETTER_INSTALL_REEXEC:-0}" != "1" && "$_SELF_HASH_BEFORE" != "$_SELF_HASH_AFTER" ]]; then
    log_warn "install.sh wurde durch das Source-Update verändert — Neustart mit aktualisiertem Skript (re-exec)."
    export WETTER_INSTALL_REEXEC=1
    exec bash "$_SELF_PATH" "${_ORIG_ARGV[@]}"
fi

restore_runtime_overrides
log_runtime_overrides_sha_after

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
    echo "  train_data/statistics/  (Langzeitstatistik und Klimatologie-Raster)"
    echo "  train_data/hydro/       (Hydro-Live-/Impactdaten und lokale Hydro-Geodaten)"
    echo "  .env                    (Zugangsdaten: FTP, Blitzortung, Twilio)"
    echo "  runtime_overrides.json  (Admin-Panel-Einstellungen)"
    echo "  users.db                (Benutzerkonten und Passwörter — bleiben immer erhalten)"
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

    # ── users.db WIRD ERHALTEN — Benutzerkonten und Passwörter bleiben bestehen ──
    if [[ -f "${TARGET}/users.db" ]]; then
        _user_count=$(python3 -c "
import sqlite3, sys
try:
    c = sqlite3.connect('${TARGET}/users.db')
    n = c.execute('SELECT COUNT(*) FROM users WHERE active=1').fetchone()[0]
    print(n)
    c.close()
except Exception:
    print('?')
" 2>/dev/null || echo "?")
        log_info "users.db erhalten: ${_user_count} aktive Benutzer bleiben bestehen."
    fi

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
log_info "Stelle HitL- und Zell-Lineage-Verzeichnisse sicher (bestehende Daten bleiben unberührt)..."
mkdir -p "${TARGET}/train_data/cell_filters/polygons"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${TARGET}/train_data/cell_filters" 2>/dev/null || true
chmod 755 "${TARGET}/train_data/cell_filters" "${TARGET}/train_data/cell_filters/polygons" 2>/dev/null || true
if mkdir -p "${TARGET}/train_data/cell_lineage"; then
    chown -R "${SERVICE_USER}:${SERVICE_USER}" "${TARGET}/train_data/cell_lineage" 2>/dev/null || true
    chmod 755 "${TARGET}/train_data/cell_lineage" 2>/dev/null || true
    log_info "  ${TARGET}/train_data/cell_lineage/      (Zell-Lineage — bleibt erhalten)"
else
    log_warn "Konnte ${TARGET}/train_data/cell_lineage nicht anlegen; Zell-Lineage wird beim Schreiben erneut versuchen."
fi

# P-S02: Langzeitstatistik-Verzeichnis anlegen (beide Modi, idempotent).
mkdir -p "${TARGET}/train_data/statistics"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${TARGET}/train_data/statistics" 2>/dev/null || true

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
    # B124: journald unterstützt KEIN Per-Unit-Vacuum (--vacuum-* ignoriert --unit).
    # Korrekt: aktives Journal per --rotate archivieren, dann ALLE Archive global
    # per --vacuum-time=1s entfernen. Auf dem dedizierten Wetter-Pi ist das
    # vollständige Leeren des Journals gewollt.
    log_info "Leere systemd Journal-Logs (global rotate + vacuum)..."
    sudo journalctl --rotate 2>/dev/null || true
    sleep 1
    sudo journalctl --vacuum-time=1s 2>/dev/null || true
    log_info "Journal geleert."

    # B124: nginx-Zugriffs-/Fehler-Logs ebenfalls leeren — sonst zeigt der
    # Debug-Export/das Adminpanel nach der Neuinstallation weiterhin alte
    # nginx-Zeilen. truncate behält die Inode → nginx neu öffnen lassen.
    for _nlog in /var/log/nginx/access.log /var/log/nginx/error.log; do
        if [[ -f "$_nlog" ]]; then
            sudo truncate -s 0 "$_nlog" 2>/dev/null \
                || sudo sh -c ": > '$_nlog'" 2>/dev/null || true
        fi
    done
    # nginx die Log-Handles neu öffnen lassen (sonst schreibt es an alte Offsets).
    sudo systemctl reload nginx 2>/dev/null || sudo nginx -s reopen 2>/dev/null || true
    log_info "nginx-Logs geleert."

    _eval_dir="$TARGET/train_data/evaluation"
    if [[ -d "$_eval_dir" ]]; then
        log_info "Leere Evaluation-Logs in $_eval_dir ..."
        rm -f \
            "$_eval_dir/api_health.jsonl" \
            "$_eval_dir/api_call_counts.jsonl" \
            "$_eval_dir/cleanup_log.jsonl" \
            "$_eval_dir/cells_log.jsonl" \
            "$_eval_dir/eumetview_debug.jsonl" \
            "$_eval_dir/log_clear_state.json"
        # KI-Analyse-Vorschläge (ai_suggestions/) ebenfalls leeren
        if [[ -d "$_eval_dir/ai_suggestions" ]]; then
            rm -f "$_eval_dir/ai_suggestions"/*.json 2>/dev/null || true
            log_info "ai_suggestions geleert."
        fi
        log_info "Evaluation-Logs geleert (inkl. eumetview_debug.jsonl, log_clear_state.json)."
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
        git curl wget openssh-client build-essential
        libgdal-dev gdal-bin unzip     # für rasterio und Hydro-Static-OGR
        libatlas-base-dev              # NumPy BLAS auf Pi
        libopencv-dev                  # OpenCV system-libs
        libhdf5-dev                    # TensorFlow h5
        libffi-dev libssl-dev          # pip wheel builds
        libjpeg-dev zlib1g-dev         # Pillow
        ffmpeg                         # movement.gif
        nginx                          # Reverse-Proxy für Flask-API + React-Frontend
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
    "$VENV/bin/pip" install --no-cache-dir "${ARGS[@]}" 2>&1 | tail -5
    if [[ "${PIPESTATUS[0]}" -eq 0 ]]; then        # B178: echter pip-Exit, nicht tail
        return 0
    fi

    log_warn "Stufe 1 fehlgeschlagen — versuche mit --trusted-host..."
    "$VENV/bin/pip" install --no-cache-dir \
            --trusted-host pypi.org \
            --trusted-host pypi.python.org \
            --trusted-host files.pythonhosted.org \
            "${ARGS[@]}" 2>&1 | tail -5
    if [[ "${PIPESTATUS[0]}" -eq 0 ]]; then        # B178: echter pip-Exit, nicht tail
        log_warn "Installation mit --trusted-host erfolgreich (SSL-Bypass aktiv)."
        return 0
    fi

    log_warn "Stufe 2 fehlgeschlagen — Bootstrap-Versuch..."
    if pip_bootstrap; then
        "$VENV/bin/pip" install --no-cache-dir \
                --trusted-host pypi.org \
                --trusted-host pypi.python.org \
                --trusted-host files.pythonhosted.org \
                "${ARGS[@]}" 2>&1 | tail -5
        if [[ "${PIPESTATUS[0]}" -eq 0 ]]; then    # B178: echter pip-Exit, nicht tail
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
    # B178: Kritische wissenschaftliche Abhängigkeiten verifizieren — ein still
    # fehlgeschlagener Build (z. B. pysteps/scipy auf aarch64) darf nicht unbemerkt
    # bleiben (zieldefinition: install.sh muss den Zustand am Raspberry prüfen).
    _CRIT_IMPORTS="numpy scipy pysteps cv2 lightgbm shapely rasterio filterpy apscheduler flask simplekml"
    _MISSING_IMPORTS=""
    for _mod in $_CRIT_IMPORTS; do
        if ! "$VENV/bin/python3" -c "import $_mod" 2>/dev/null; then
            _MISSING_IMPORTS="$_MISSING_IMPORTS $_mod"
        fi
    done
    if [[ -n "$_MISSING_IMPORTS" ]]; then
        log_warn "Kritische Module NICHT importierbar:$_MISSING_IMPORTS"
        note_manual "source $VENV/bin/activate && pip install --upgrade pip wheel setuptools && pip install$_MISSING_IMPORTS"
        note_manual "pysteps baut auf aarch64 ggf. nur via Git: pip install git+https://github.com/pySTEPS/pysteps"
    else
        check_ok "Kritische Module importierbar (numpy/scipy/pysteps/cv2/lightgbm/shapely/rasterio/filterpy/apscheduler/flask/simplekml)."
    fi
    if [[ -z "$_MISSING_IMPORTS" ]]; then
        log_info "Teste pySTEPS Lucas-Kanade Funktion..."
        if "$VENV/bin/python3" - <<'PY'
import numpy as np
from pysteps.motion.lucaskanade import dense_lucaskanade

# Synthetische Radar-Sequenz: kleiner Regenblock verschiebt sich nach rechts.
# Keine externen Dateien, keine externen Requests.
R = np.zeros((2, 64, 64), dtype=np.float32)
R[0, 22:34, 20:32] = 1.0
R[1, 22:34, 24:36] = 1.0

# pySTEPS ignoriert fehlende/irrelevante Bereiche über NaN.
R = np.where(R < 0.01, np.nan, R)

UV = dense_lucaskanade(R)

assert UV.shape[0] == 2, UV.shape
assert UV.shape[1] == 64, UV.shape
assert UV.shape[2] == 64, UV.shape

print("OK: pySTEPS Lucas-Kanade Funktionstest:", UV.shape)
PY
        then
            check_ok "pySTEPS Lucas-Kanade Funktionstest erfolgreich."
        else
            log_warn "pySTEPS Lucas-Kanade Funktionstest fehlgeschlagen."
            note_manual "cd $TARGET && source venv/bin/activate && pip install --upgrade numpy scipy pysteps"
            note_manual "Auf Raspberry Pi/aarch64 ggf.: pip install git+https://github.com/pySTEPS/pysteps"
            note_manual "Danach erneut prüfen: $VENV/bin/python3 -c 'from pysteps.motion.lucaskanade import dense_lucaskanade; print(\"OK\")'"
        fi
    fi
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
    train_data/cell_lineage
    train_data/lightning
    train_data/evaluation
    train_data/cloud
    train_data/arome
    train_data/api_cache
    train_data/dem
    train_data/hydro/static
    train_data/hydro/static/source
    train_data/hydro/static/generated
    train_data/hydro/live
    train_data/hydro/impact
    data/config
    data/radar
    data
    logs
)
for d in "${DIRS[@]}"; do
    mkdir -p "$TARGET/$d"
done
log_info "Verzeichnisstruktur erstellt."

if [[ ! -f "$TARGET/train_data/hydro/static/generated/station_catchments.geojson" || ! -f "$TARGET/train_data/hydro/static/generated/station_network_index.json" ]]; then
    log_warn "Hydro-Impact benötigt lokale Gewässer-/Einzugsgebietsdaten."
    log_warn "Installation wird fortgesetzt; lege GeoJSON-Quellen unter train_data/hydro/static/source/ ab und baue sie später über den Hydro-Static-Import."
fi

# ============================================================================== 
# PHASE 6a — Hydro-Static automatisch installieren (nur Full-Modus)
# ============================================================================== 
if [[ "$MODE" == "full" ]]; then
    CURRENT_PHASE="Phase 6a — Hydro-Static automatisch installieren"
    log_step "Phase 6a — Hydro-Static automatisch installieren"
    HYDRO_STATIC_PKGS=(gdal-bin unzip curl jq)
    log_info "Prüfe Hydro-Static-Systemwerkzeuge: ${HYDRO_STATIC_PKGS[*]}"
    for _tool in curl jq unzip ogrinfo ogr2ogr; do
        command -v "$_tool" >/dev/null 2>&1 || log_warn "Hydro-Static-Werkzeug fehlt: $_tool"
    done
    if command -v ogr2ogr >/dev/null 2>&1 && command -v ogrinfo >/dev/null 2>&1; then
        ogr2ogr --version || true
        ogrinfo --version || true
    else
        log_warn "GDAL/OGR nicht vollständig verfügbar; installiere im Full-Modus über APT, falls System-Dependencies aktiv sind."
        if [[ "$SYSTEM_DEPS_ENABLED" == true ]]; then
            sudo apt-get install -y "${HYDRO_STATIC_PKGS[@]}" 2>&1 | grep -E "^(Inst|Err)" || true
        fi
    fi
    PYTHON="$VENV/bin/python3"
    [[ -x "$PYTHON" ]] || PYTHON="python3"
    HYDRO_AUTO_ARGS=(--auto)
    [[ "$FORCE_DOWNLOAD" == true ]] && HYDRO_AUTO_ARGS+=(--force)
    log_info "Starte Hydro-Static Auto-Importer: $PYTHON hydro_static_import.py ${HYDRO_AUTO_ARGS[*]}"
    if "$PYTHON" "$TARGET/hydro_static_import.py" --auto ${HYDRO_AUTO_ARGS[@]:1}; then
        log_info "Hydro-Static Auto-Importer abgeschlossen."
    else
        log_warn "Hydro-Static Auto-Importer meldete Fehler; Installation wird fortgesetzt."
    fi
    if "$PYTHON" "$TARGET/hydro_static_import.py" --check-coverage feldkirchen >/dev/null; then
        log_info "Hydro-Static Feldkirchen-Coverage gespeichert."
    else
        log_warn "Hydro-Static Feldkirchen-Coverage konnte nicht vollständig validiert werden."
    fi
    set +e
    "$PYTHON" - <<'HYDROSTATICPY' "$TARGET/train_data/hydro/static/generated/hydro_static_status.json"
import json, sys
p=sys.argv[1]
try:
    s=json.load(open(p, encoding='utf-8'))
except Exception as exc:
    print(f"Hydro-Static Status: invalid_static_json ({exc})")
    raise SystemExit(2)
downloads=s.get('downloads') or {}
dstates=','.join(sorted({str(v.get('status')) for v in downloads.values() if isinstance(v, dict)})) or 'skipped'
print(f"Hydro-Static Status: {s.get('status')}")
print(f"Live-Hydro Stationen: {s.get('live_station_count', s.get('station_count', 0))}")
print(f"Statische Stationen: {s.get('static_station_count', s.get('station_count', 0))}")
print(f"Basins: {s.get('basin_count', 0)}")
print(f"Flowlines: {s.get('flowline_count', 0)}")
print(f"Impact-fähige Stationen: {s.get('impact_eligible_station_count', 0)}")
coverage=s.get("feldkirchen_coverage") or {}
print(f"Feldkirchen-Abdeckung: {coverage.get('coverage_ok', False)}")
print(f"Downloads: {dstates}")
missing=s.get('missing') or []
if missing: print("Fehlende Dateien: " + ", ".join(map(str, missing)))
for err in s.get('errors') or []: print(f"Hydro-Static Fehler: {err}")
for warn in s.get('warnings') or []: print(f"Hydro-Static Hinweis: {warn}")
if s.get("status") in {"hydro_static_download_failed", "hydro_static_convert_failed", "hydro_station_import_failed", "hydro_static_missing", "invalid_static_json"}:
    raise SystemExit(2)
HYDROSTATICPY
    _HYDRO_STATUS_RC=$?
    set -e
    if [[ $_HYDRO_STATUS_RC -ne 0 ]]; then
        log_warn "Hydro-Static konnte nicht vollständig automatisch eingerichtet werden."
        note_manual "cd $TARGET && source venv/bin/activate"
        note_manual "sudo apt-get update && sudo apt-get install -y gdal-bin unzip curl jq"
        note_manual "python3 hydro_static_import.py --auto --force"
        note_manual "Falls Downloads weiter fehlschlagen: curl -L -o train_data/hydro/static/source/_downloads/AT_DRAINAGEBASIN_GDB.zip https://inspire.lfrz.gv.at/000801/ds/AT_DRAINAGEBASIN_GDB.zip && python3 hydro_static_import.py --auto"
    fi
fi

# Size-Regressor-Kompatibilität prüfen, ohne Trainings-/Hydro-/Langzeitdaten zu löschen.
SIZE_REG_MODEL="$TARGET/models/size_regressor.pkl"
SIZE_REG_META="$TARGET/models/size_regressor_meta.json"
if [[ -f "$SIZE_REG_MODEL" || -f "$SIZE_REG_META" ]]; then
    _SIZE_MODEL_FEATURES=""
    _SIZE_SCHEMA_VERSION=""
    if [[ -f "$SIZE_REG_META" ]]; then
        _SIZE_MODEL_FEATURES=$("$VENV/bin/python3" - <<'PY' "$SIZE_REG_META" 2>/dev/null || true
import json, sys
try:
    meta=json.load(open(sys.argv[1], encoding='utf-8'))
    print(meta.get('feature_count') or (len(meta.get('feature_keys')) if isinstance(meta.get('feature_keys'), list) else ''))
except Exception:
    print('')
PY
)
        _SIZE_SCHEMA_VERSION=$("$VENV/bin/python3" - <<'PY' "$SIZE_REG_META" 2>/dev/null || true
import json, sys
try:
    print(json.load(open(sys.argv[1], encoding='utf-8')).get('feature_schema_version') or '')
except Exception:
    print('')
PY
)
    fi
    if [[ -n "$_SIZE_MODEL_FEATURES" && "$_SIZE_MODEL_FEATURES" != "15" ]]; then
        log_warn "Size-Regressor inkompatibel: model_features=${_SIZE_MODEL_FEATURES} current_features=15."
        log_warn "Geometrischer Fallback aktiv. Retraining wird bei genug Labels gestartet."
    elif [[ -n "$_SIZE_SCHEMA_VERSION" && "$_SIZE_SCHEMA_VERSION" != "2" ]]; then
        log_warn "Size-Regressor Feature-Schema-Version abweichend: model_schema=${_SIZE_SCHEMA_VERSION} current_schema=2."
        log_warn "Geometrischer Fallback aktiv, falls die Runtime das Modell als inkompatibel erkennt."
    fi
fi

INITIAL_MODEL_SOURCE="$TARGET/weather_lstm_model.keras"
INITIAL_MODEL_TARGET="$TARGET/train_data/models/current/weather_lstm.keras"
if [[ -n "${RESET_ML_MODE:-}" && -f "$TARGET/ml_reset.py" ]]; then
    log_info "ML-Reset per install.sh angefordert: $RESET_ML_MODE"
    ( cd "$TARGET" && "$VENV/bin/python3" - <<PY
from ml_reset import reset_ml
print(reset_ml("$RESET_ML_MODE")["reset"]["status"])
PY
    ) || { log_error "ML-Reset fehlgeschlagen"; exit 1; }
fi

if [[ -f "$TARGET/train_data/ml_reset_status.json" ]]; then
    log_info "ML-Reset-Status vorhanden — Initialmodell-Bootstrap wird nicht reaktiviert."
elif [[ -f "$INITIAL_MODEL_SOURCE" ]]; then
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

# ── JWT-Authentifizierung ─────────────────────────────────────
# Wird automatisch von install.sh generiert (openssl rand -hex 32).
# Bei Neustart ohne JWT_SECRET: zufälliger Secret → alle Sessions ungültig.
JWT_SECRET=

# ── Debug-Modus ───────────────────────────────────────────────
WETTER_DEBUG=0
ALLOW_SYSTEM_LOG_PURGE=false
ENVTEMPLATE
        log_warn ".env angelegt — Credentials eintragen:"
        note_manual "nano $ENV_FILE  # FTP, BLITZ, TWILIO, ANTHROPIC_API_KEY, GITHUB_TOKEN setzen"
    fi

    # JWT_SECRET generieren (einmalig, bei Upgrade beibehalten)
    # Wird von auth.py fuer JWT-Signierung verwendet.
    EXISTING_JWT_SECRET=$(grep "^JWT_SECRET=" "$ENV_FILE" 2>/dev/null | cut -d= -f2 | tr -d ' ' || true)
    if [[ -z "$EXISTING_JWT_SECRET" ]]; then
        NEW_JWT_SECRET=$(openssl rand -hex 32)
        sed -i '/^JWT_SECRET=$/d' "$ENV_FILE"
        echo "JWT_SECRET=${NEW_JWT_SECRET}" >> "$ENV_FILE"
        check_ok ".env: JWT_SECRET generiert ($(echo "${NEW_JWT_SECRET}" | cut -c1-8)...)"
    else
        check_ok ".env: JWT_SECRET vorhanden"
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

    # JWT_SECRET generieren (einmalig, bei Upgrade beibehalten)
    # Wird von auth.py fuer JWT-Signierung verwendet.
    EXISTING_JWT_SECRET=$(grep "^JWT_SECRET=" "$ENV_FILE" 2>/dev/null | cut -d= -f2 | tr -d ' ' || true)
    if [[ -z "$EXISTING_JWT_SECRET" ]]; then
        NEW_JWT_SECRET=$(openssl rand -hex 32)
        sed -i '/^JWT_SECRET=$/d' "$ENV_FILE"
        echo "JWT_SECRET=${NEW_JWT_SECRET}" >> "$ENV_FILE"
        check_ok ".env: JWT_SECRET generiert ($(echo "${NEW_JWT_SECRET}" | cut -c1-8)...)"
    else
        check_ok ".env: JWT_SECRET vorhanden"
    fi
    if ! grep -q "^ALLOW_SYSTEM_LOG_PURGE=" "$ENV_FILE" 2>/dev/null; then
        echo "ALLOW_SYSTEM_LOG_PURGE=false" >> "$ENV_FILE"
        check_ok ".env: ALLOW_SYSTEM_LOG_PURGE=false ergänzt"
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
        npm ${_NPM_CMD} --no-audit --no-fund 2>&1 | tail -3
        if [[ "${PIPESTATUS[0]}" -eq 0 ]]; then
            log_info "npm run build..."
            NODE_OPTIONS="--max-old-space-size=2048" npm run build 2>&1 | tail -5
            if [[ "${PIPESTATUS[0]}" -eq 0 ]]; then
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

# .admin_password: Passwort fuer initialen Superadmin sicherstellen.
# Wird von auth.py / init_db() beim ersten App-Start gelesen.
ADMIN_PASS_FILE="$TARGET/.admin_password"
if [[ ! -f "$ADMIN_PASS_FILE" ]]; then
    ADMIN_PASS=$(openssl rand -base64 16 | tr -d '/+=\n' | head -c 16)
    echo "$ADMIN_PASS" > "$ADMIN_PASS_FILE"
    chmod 600 "$ADMIN_PASS_FILE"
    check_ok "Admin-Passwort generiert → $ADMIN_PASS_FILE"
    echo -e "${YELLOW}  Admin-Passwort (Erstlogin): ${ADMIN_PASS}${NC}"
    echo -e "${YELLOW}  (auch gespeichert in: $ADMIN_PASS_FILE)${NC}"
    echo -e "${YELLOW}  Login: http://<pi-ip>/ → Benutzer: admin${NC}"
else
    log_info ".admin_password vorhanden — Passwort unverändert."
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

    log_info "Generiere nginx-Konfiguration: $NGINX_SITE_CONF"
    sudo tee "$NGINX_SITE_CONF" > /dev/null <<NGINXCONF
# WetterExtended — nginx Reverse-Proxy
# Generiert von install.sh am $(date '+%Y-%m-%d %H:%M:%S')
# Authentifizierung: JWT via Flask (auth.py) — kein nginx Basic-Auth mehr.

# ── Rate-Limiting: Schutz gegen Reconnaissance-Scans und Brute-Force ──────
# 60r/m = 1 req/s Durchschnitt; burst=30 erlaubt Page-Load-Bursts.
# Überschreitung → HTTP 429 (Too Many Requests).
limit_req_zone \$binary_remote_addr zone=wetter_api:10m rate=60r/m;
limit_req_zone \$binary_remote_addr zone=wetter_auth:10m rate=10r/m;
# Eigene grosszuegige Zone fuer geschuetzte Admin-Export-Polls/Downloads.
limit_req_zone \$binary_remote_addr zone=wetter_admin_export:10m rate=30r/m;

server {
    listen 80;
    listen [::]:80;
    server_name _;

    root ${FRONTEND_DIST};
    index index.html;

    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml image/svg+xml;
    gzip_min_length 1024;

    location / {
        try_files \$uri \$uri/ /index.html;
        add_header Cache-Control "no-cache";
    }

    # Vollbild-Karte: oeffentlich (Flask behandelt Auth fuer alle API-Requests)
    # Regex-Match deckt /karte, /karte/ und /karte/* ab (Trailing-Slash-Fix)
    location ~ ^/karte(/.*)?$ {
        try_files \$uri /index.html;
        add_header Cache-Control "no-cache";
    }

    # Favicon
    location = /favicon.ico {
        expires 1y;
        add_header Cache-Control "public, immutable";
        try_files \$uri =404;
    }

    # Leaflet-Assets + Frontend-Assets (statisch, kein Auth)
    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # Debug-Export kann auf kleinen Raspberry-Pi-Systemen laenger laufen.
    # Exakte Locations muessen vor der allgemeinen /api/-Location stehen, damit
    # Admin-Export-Polling nicht mit Karten-/Radar-/Forecast-Bursts in wetter_api konkurriert.
    # Auth/Rollenpruefung bleibt unveraendert in Flask/JWT aktiv.
    location ~ ^/api/admin/export/(last-24h/parts|status|download|part|last-24h\.zip)$ {
        # Geschuetzte Admin-Export-Endpunkte bekommen eine eigene grosszuegige
        # Zone statt der engen Karten-API-Zone.
        limit_req zone=wetter_admin_export burst=120 nodelay;
        limit_req_status 429;

        proxy_pass         http://127.0.0.1:5000\$request_uri;
        proxy_http_version 1.1;
        proxy_set_header   Host              \$host;
        proxy_set_header   X-Real-IP         \$remote_addr;
        proxy_set_header   X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto \$scheme;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
        proxy_connect_timeout 10s;
        proxy_buffering off;
    }

    # Logs/Admin-Liveansicht separat, damit Polling nicht mit Karten-/Radar-Bursts konkurriert.
    location = /api/logs {
        proxy_pass         http://127.0.0.1:5000/api/logs;
        proxy_http_version 1.1;
        proxy_set_header   Host              \$host;
        proxy_set_header   X-Real-IP         \$remote_addr;
        proxy_set_header   X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
        proxy_connect_timeout 10s;
    }

    location = /api/logs/capabilities {
        proxy_pass         http://127.0.0.1:5000/api/logs/capabilities;
        proxy_http_version 1.1;
        proxy_set_header   Host              \$host;
        proxy_set_header   X-Real-IP         \$remote_addr;
        proxy_set_header   X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
        proxy_connect_timeout 10s;
    }

    # Alle API-Endpunkte an Flask weiterleiten.
    # Flask (auth.py / _jwt_auth_check) entscheidet welche Endpunkte Auth benoetigen.
    # GET-Requests sind oeffentlich; POST/PATCH/DELETE benoetigen JWT Bearer Token.
    location /api/ {
        # Rate-Limiting: 60 req/min Avg, Burst 30 — ausreichend für normalen
        # Admin-Betrieb (Page-Load ~12 req, Polling ~4 req/min).
        # Reconnaissance-Scanner (30+ req/5s) werden nach Burst-Aufbrauchen
        # mit HTTP 429 abgewiesen und durch fail2ban dauerhaft blockiert.
        limit_req zone=wetter_api burst=30 nodelay;
        limit_req_status 429;

        proxy_pass         http://127.0.0.1:5000/api/;
        proxy_http_version 1.1;
        proxy_set_header   Host              \$host;
        proxy_set_header   X-Real-IP         \$remote_addr;
        proxy_set_header   X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
        proxy_connect_timeout 10s;
    }

    # Auth-Endpunkte: strengeres Rate-Limit gegen Credential-Stuffing
    location /api/auth/login {
        limit_req zone=wetter_auth burst=5 nodelay;
        limit_req_status 429;

        proxy_pass         http://127.0.0.1:5000/api/auth/login;
        proxy_http_version 1.1;
        proxy_set_header   Host              \$host;
        proxy_set_header   X-Real-IP         \$remote_addr;
        proxy_set_header   X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto \$scheme;
        proxy_read_timeout 30s;
        proxy_connect_timeout 10s;
    }

    # Finding #4 Fix: /export/ ist keine Flask-Route.
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
# PHASE 7e — fail2ban: Schutz gegen Reconnaissance und Brute-Force
# ==============================================================================
CURRENT_PHASE="Phase 7e — fail2ban"
log_step "Phase 7e — fail2ban"

if command -v apt-get &>/dev/null; then

    if ! command -v fail2ban-client &>/dev/null; then
        log_info "Installiere fail2ban..."
        sudo apt-get install -y fail2ban > /dev/null 2>&1 \
            && check_ok "fail2ban installiert" \
            || check_warn "fail2ban Installation fehlgeschlagen — manuell nachinstallieren"
    else
        log_info "fail2ban bereits installiert."
    fi

    # ── Filter: Erkennt Reconnaissance-Bursts (viele 404s von einer IP) ──────
    sudo tee /etc/fail2ban/filter.d/nginx-recon.conf > /dev/null <<'FAIL2BAN_FILTER'
[Definition]
# Erkennt automatisierte Reconnaissance-Scans: viele 404-Antworten von einer IP.
# Passt auf nginx combined/main log-Format.
failregex = ^<HOST> .* "(?:GET|POST|HEAD|PUT|DELETE|OPTIONS|PATCH) [^ ]* HTTP/\d+\.\d+" 404

# Keine False-Positives für bekannte Pfade ausschließen — 404 ist 404.
ignoreregex =
FAIL2BAN_FILTER
    check_ok "fail2ban Filter nginx-recon.conf erstellt"

    # ── Jail-Konfiguration ─────────────────────────────────────────────────
    sudo tee /etc/fail2ban/jail.d/wetterprojekt.conf > /dev/null <<'FAIL2BAN_JAIL'
[DEFAULT]
# Lokale IPs niemals bannen
ignoreip = 127.0.0.1/8 ::1

[nginx-recon]
enabled   = true
filter    = nginx-recon
port      = http,https,81
logpath   = /var/log/nginx/access.log
# Ban nach 20 404s innerhalb von 60 Sekunden
maxretry  = 20
findtime  = 60
# Ban-Dauer: 1 Stunde; bei Wiederholung empfiehlt sich manuelles permanentes Ban
bantime   = 3600
action    = iptables-multiport[name=nginx-recon, port="80,81,443", protocol=tcp]

[nginx-ratelimit]
# Banniert IPs die nginx Rate-Limit (429) auslösen — diese sind aktive Scanner
enabled   = true
filter    = nginx-limit-req
port      = http,https,81
logpath   = /var/log/nginx/error.log
maxretry  = 10
findtime  = 60
bantime   = 7200
FAIL2BAN_JAIL
    check_ok "fail2ban Jail wetterprojekt.conf erstellt"

    # ── fail2ban aktivieren und starten ──────────────────────────────────
    sudo systemctl enable fail2ban > /dev/null 2>&1
    if sudo systemctl is-active --quiet fail2ban 2>/dev/null; then
        sudo fail2ban-client reload > /dev/null 2>&1 \
            && check_ok "fail2ban: Konfiguration neu geladen" \
            || check_warn "fail2ban reload fehlgeschlagen — bitte manuell prüfen"
    else
        sudo systemctl start fail2ban > /dev/null 2>&1 \
            && check_ok "fail2ban gestartet" \
            || check_warn "fail2ban konnte nicht gestartet werden"
    fi

    # ── Nginx-Logging für fail2ban sicherstellen ──────────────────────────
    # Raspberry Pi OS: nginx access_log ist per Default aktiv in /etc/nginx/nginx.conf
    if [[ -f /var/log/nginx/access.log ]]; then
        check_ok "nginx access.log vorhanden: $(wc -l < /var/log/nginx/access.log 2>/dev/null || echo '?') Zeilen"
    else
        check_warn "nginx access.log fehlt — fail2ban kann nginx-recon nicht überwachen"
        note_manual "sudo nginx -t && sudo systemctl reload nginx"
    fi

else
    check_warn "apt-get nicht verfügbar — fail2ban übersprungen."
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

    # Sicheres Log-Purge-Skript + sudoers (nur dieses eine Kommando)
    PURGE_SCRIPT_SRC="$TARGET/scripts/wetterprojekt-purge-logs.sh"
    PURGE_SCRIPT_DST="/usr/local/bin/wetterprojekt-purge-logs.sh"
    if [[ -f "$PURGE_SCRIPT_SRC" ]]; then
        sudo install -o root -g root -m 0750 "$PURGE_SCRIPT_SRC" "$PURGE_SCRIPT_DST"
        check_ok "Log-Purge-Skript installiert: $PURGE_SCRIPT_DST"
        SUDOERS_FILE="/etc/sudoers.d/wetterprojekt-logs"
        echo "${SERVICE_USER} ALL=(root) NOPASSWD: ${PURGE_SCRIPT_DST}" | sudo tee "$SUDOERS_FILE" >/dev/null
        sudo chmod 0440 "$SUDOERS_FILE"
        if sudo visudo -cf "$SUDOERS_FILE" >/dev/null; then
            check_ok "sudoers-Regel validiert: $SUDOERS_FILE"
        else
            sudo rm -f "$SUDOERS_FILE"
            log_error "Ungültige sudoers-Regel entfernt: $SUDOERS_FILE"
            exit 1
        fi
    else
        check_warn "Purge-Skript fehlt: $PURGE_SCRIPT_SRC"
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
    # Upgrade-Modus: ALLE drei Services zwingend neu starten — unabhängig davon
    # ob sie vorher liefen. Neuer Code + neue pip-Pakete werden erst nach
    # Prozess-Neustart wirksam. Garantiert dass Fixes nach jedem Upgrade aktiv sind.
    log_info "Starte alle Wetterprojekt-Services neu (erzwungen)..."
    sudo systemctl daemon-reload 2>/dev/null || true
    for _svc in wetterprojekt wetterprojekt-scheduler wetterprojekt-admin; do
        sudo systemctl reset-failed "$_svc" 2>/dev/null || true
        if sudo systemctl restart "$_svc" 2>/dev/null; then
            sleep 2
            systemctl is-active --quiet "$_svc" \
                && check_ok "$_svc neu gestartet" \
                || check_warn "$_svc gestartet aber nicht aktiv — prüfen: journalctl -u $_svc -n 20"
        else
            log_warn "$_svc konnte nicht (neu) gestartet werden"
            note_manual "sudo systemctl restart $_svc && journalctl -u $_svc -n 30"
        fi
    done

    # API-Fehler-Log nach Upgrade leeren — Admin-Panel zeigt sauberen Start.
    # Alteinträge (z.B. HTTP-400 vor dem Fix) verschwinden sofort statt erst
    # nach 24 Stunden. Reine Log-Datei, keine Trainingsdaten.
    _api_log="$TARGET/train_data/evaluation/api_health.jsonl"
    if [[ -f "$_api_log" ]]; then
        : > "$_api_log"
        check_ok "API-Fehler-Log geleert (frischer Start nach Upgrade)"
    fi
    # log_clear_state.json aktualisieren → Admin-Panel zeigt "seit HH:MM" korrekt
    python3 -c "
import json, os, datetime
p = '$TARGET/train_data/evaluation/log_clear_state.json'
os.makedirs(os.path.dirname(p), exist_ok=True)
with open(p, 'w') as f:
    json.dump({'cleared_at_utc': datetime.datetime.utcnow().isoformat() + 'Z'}, f)
" 2>/dev/null || true
fi

# ==============================================================================
# PHASE 7f — Debug-Export-Branch-Timer
# ==============================================================================
CURRENT_PHASE="Phase 7f — Debug-Export-Branch"
log_step "Phase 7f — Debug-Export-Branch"

DEBUG_EXPORT_TIMER="wetterprojekt-debug-export-branch.timer"
DEBUG_EXPORT_SERVICE="wetterprojekt-debug-export-branch.service"
DEBUG_EXPORT_STATUS="deaktiviert"

if [[ "$MODE" == "full" && "$ENABLE_DEBUG_EXPORT_GIT" == true ]]; then
    DEBUG_EXPORT_SCRIPT="$TARGET/tools/publish_latest_debug_export_branch.py"
    if [[ ! -f "$DEBUG_EXPORT_SCRIPT" ]]; then
        check_warn "Debug-Export-Publisher fehlt: $DEBUG_EXPORT_SCRIPT"
        note_manual "Debug-Export-Publisher fehlt. Source aktualisieren und erneut ausführen: $0 --mode full"
    else
        DEBUG_EXPORT_SERVICE_SRC="$TARGET/$DEBUG_EXPORT_SERVICE"
        DEBUG_EXPORT_TIMER_SRC="$TARGET/$DEBUG_EXPORT_TIMER"
        if [[ -f "$DEBUG_EXPORT_SERVICE_SRC" && -f "$DEBUG_EXPORT_TIMER_SRC" ]]; then
            DEBUG_EXPORT_SERVICE_GEN="$TARGET/.generated-$DEBUG_EXPORT_SERVICE"
            sed -e "s|^User=.*|User=$SERVICE_USER|g" \
                -e "s|^WorkingDirectory=.*|WorkingDirectory=$TARGET|g" \
                -e "s|^Environment=WETTER_DEBUG_EXPORT_BRANCH=.*|Environment=WETTER_DEBUG_EXPORT_BRANCH=$DEBUG_EXPORT_BRANCH|g" \
                -e "s|^Environment=WETTER_DEBUG_EXPORT_TARGET_PATH=.*|Environment=WETTER_DEBUG_EXPORT_TARGET_PATH=$DEBUG_EXPORT_TARGET_PATH|g" \
                -e "s|^Environment=WETTER_DEBUG_EXPORT_MAX_SOURCE_TOTAL_MB=.*|Environment=WETTER_DEBUG_EXPORT_MAX_SOURCE_TOTAL_MB=$DEBUG_EXPORT_MAX_SOURCE_TOTAL_MB|g" \
                -e "s|^Environment=WETTER_DEBUG_EXPORT_MAX_ZIP_MB=.*|Environment=WETTER_DEBUG_EXPORT_MAX_ZIP_MB=$DEBUG_EXPORT_MAX_ZIP_MB|g" \
                -e "s|/home/ki-pi/wetterprojekt|$TARGET|g" \
                "$DEBUG_EXPORT_SERVICE_SRC" > "$DEBUG_EXPORT_SERVICE_GEN"
            sudo cp "$DEBUG_EXPORT_SERVICE_GEN" "/etc/systemd/system/$DEBUG_EXPORT_SERVICE"
            sudo cp "$DEBUG_EXPORT_TIMER_SRC" "/etc/systemd/system/$DEBUG_EXPORT_TIMER"
            sudo systemctl daemon-reload
            check_ok "Debug-Export-Service/Timer installiert"

            if [[ ! -d "$TARGET/.git" ]]; then
                check_warn "Debug-Export: kein Git-Checkout ($TARGET/.git fehlt) — Timer wird nicht aktiviert"
                note_manual "Für automatischen GitHub-Debug-Export Projekt per Git mit origin-Remote installieren: git clone $REPO $TARGET"
            else
                DEBUG_EXPORT_CHECK_LOG="$TARGET/train_data/evaluation/debug_export_branch_check.log"
                mkdir -p "$(dirname "$DEBUG_EXPORT_CHECK_LOG")"
                log_info "Prüfe GitHub-Write-Zugriff für Debug-Export-Branch..."
                set +e
                trap '' ERR
                "$VENV/bin/python3" "$DEBUG_EXPORT_SCRIPT" \
                    --repo-dir "$TARGET" \
                    --branch "$DEBUG_EXPORT_BRANCH" \
                    --target-path "$DEBUG_EXPORT_TARGET_PATH" \
                    --check-only 2>&1 | tee "$DEBUG_EXPORT_CHECK_LOG"
                DEBUG_EXPORT_CHECK_RC=${PIPESTATUS[0]}
                trap on_error ERR
                set -e

                if [[ "$DEBUG_EXPORT_CHECK_RC" -eq 0 ]]; then
                    sudo systemctl enable --now wetterprojekt-debug-export-branch.timer
                    check_ok "Debug-Export-Timer aktiviert → $DEBUG_EXPORT_BRANCH"
                else
                    check_warn "GitHub-Schreibtest fehlgeschlagen — Debug-Export-Timer wird nicht aktiviert"
                    note_manual "GitHub-Schreibtest fehlgeschlagen. Bitte SSH Deploy Key oder PAT mit Write-Zugriff einrichten."
                    note_manual "Danach aktivieren: sudo systemctl enable --now wetterprojekt-debug-export-branch.timer"
                    note_manual "Test Schreibrecht: cd $TARGET && $VENV/bin/python3 $DEBUG_EXPORT_SCRIPT --repo-dir $TARGET --check-only"
                    note_manual "Test Export-Limits: cd $TARGET && $VENV/bin/python3 $DEBUG_EXPORT_SCRIPT --repo-dir $TARGET --dry-run --max-source-total-mb $DEBUG_EXPORT_MAX_SOURCE_TOTAL_MB --max-zip-mb $DEBUG_EXPORT_MAX_ZIP_MB"
                    note_manual "Details: cat $DEBUG_EXPORT_CHECK_LOG"
                fi
            fi
        else
            check_warn "Debug-Export-systemd-Templates fehlen: $DEBUG_EXPORT_SERVICE_SRC / $DEBUG_EXPORT_TIMER_SRC"
            note_manual "Debug-Export-Templates fehlen. Source aktualisieren und erneut ausführen: $0 --mode full"
        fi
    fi
elif [[ "$ENABLE_DEBUG_EXPORT_GIT" == false ]]; then
    log_info "Debug-Export-Git-Timer übersprungen (--no-debug-export-git)."
else
    log_info "Debug-Export-Git-Timer wird nur im full-Modus automatisch eingerichtet."
fi

# ==============================================================================
# PHASE 7f — Code-Fix-Verifikation
# ==============================================================================
CURRENT_PHASE="Phase 7f — Fix-Verifikation"
log_step "Phase 7f — Verifikation kritischer Fixes"

# B76: GeoSphere-Nowcast-Zeitformat darf KEIN ":00Z" mehr enthalten
if grep -q '%Y-%m-%dT%H:%M:00Z' "$TARGET/fetch_geosphere_nowcast.py" 2>/dev/null; then
    check_warn "B76 NICHT aktiv: fetch_geosphere_nowcast.py enthält noch altes Zeitformat (:00Z)"
else
    check_ok "B76 aktiv: GeoSphere-Nowcast-Zeitformat korrekt"
fi

# B78: Speed-Fix-Marker in locations_check.py + app.py
_b78=$(grep -lc "B78-FIX" "$TARGET/locations_check.py" "$TARGET/app.py" 2>/dev/null | wc -l)
if [[ "$_b78" -ge 2 ]]; then
    check_ok "B78 aktiv: Speed-Fix in locations_check.py + app.py"
else
    check_warn "B78 unvollständig: B78-FIX-Marker fehlt in locations_check.py oder app.py"
fi

# ==============================================================================
# PHASE 7g — Logs leeren
# ==============================================================================
CURRENT_PHASE="Phase 7g — Logs leeren"
log_step "Phase 7g — Logs leeren"

# api_health.jsonl immer leeren — Admin-Panel zeigt sauberen Start nach
# jedem Upgrade. Gilt für --mode=full, --mode=upgrade und ohne Parameter.
# Im full-Modus ist evaluation/ bereits gelöscht → mkdir -p sichert Existenz.
_eval_dir="$TARGET/train_data/evaluation"
_api_log="$_eval_dir/api_health.jsonl"
mkdir -p "$_eval_dir"
: > "$_api_log"
check_ok "API-Fehler-Log geleert"

# log_clear_state.json setzen → Admin-Panel zeigt "seit HH:MM" korrekt
python3 -c "
import json, os, datetime
p = '$_eval_dir/log_clear_state.json'
with open(p, 'w') as f:
    json.dump({'cleared_at_utc': datetime.datetime.utcnow().isoformat() + 'Z'}, f)
" 2>/dev/null && check_ok "log_clear_state.json gesetzt" || true

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
DEBUG_EXPORT_STATUS="$(systemctl is-enabled wetterprojekt-debug-export-branch.timer 2>/dev/null || echo 'disabled') → ${DEBUG_EXPORT_BRANCH}"

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
printf "  ${GREEN}%-20s${NC} %s\n" "Debug-Export:" "$DEBUG_EXPORT_STATUS"
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

# ── runtime_overrides.json mit Defaults initialisieren (merge-only) ──────────
echo "[INSTALL] Initialisiere runtime_overrides.json mit Default-Werten..."
PYTHON_FOR_INIT="python3"
if [[ -x "$VENV/bin/python3" ]]; then
    PYTHON_FOR_INIT="$VENV/bin/python3"
fi
if "$PYTHON_FOR_INIT" "$TARGET/init_runtime_overrides.py" --path "$TARGET/train_data/runtime_overrides.json"; then
    if verify_runtime_overrides_preserved; then
        echo "[OK] runtime_overrides.json initialisiert und bestehende Admin-Einstellungen verifiziert."
    else
        log_error "runtime_overrides.json wurde unerwartet verändert — stelle Backup wieder her."
        restore_runtime_overrides
        exit 1
    fi
else
    echo "[WARN] init_runtime_overrides.py fehlgeschlagen — runtime_overrides.json wurde nicht durch Defaults ersetzt."
    echo "       Manuell prüfen: $PYTHON_FOR_INIT $TARGET/init_runtime_overrides.py --path $TARGET/train_data/runtime_overrides.json"
    exit 1
fi

# ==============================================================================
# PHASE 8.9 — ML-Modell/Feature-Kompatibilität (B123)
# ==============================================================================
# Prüft ob die Feature-Anzahl der vorhandenen Modelle (training_meta.json →
# feature_count) zur aktuellen config.ML_NUM_FEATURES passt. Nutzt die
# kanonischen Funktionen aus model_training.py (keine Logik-Duplikate).
#   full    → inkompatible Modelle löschen (werden neu trainiert)
#   upgrade → quarantänisieren (current → current_incompatible_<ts>), kein Löschen
CURRENT_PHASE="Phase 8.9 — ML-Kompatibilität"
log_step "Phase 8.9 — ML-Modell/Feature-Kompatibilität (B123)"

if [[ -x "$VENV/bin/python3" ]]; then
    # Im Projektverzeichnis ausführen, damit config.py/model_training importierbar sind.
    _COMPAT_JSON="$( cd "$TARGET" && "$VENV/bin/python3" - <<'PYB123' 2>/dev/null
import json, os
try:
    import model_training as mt
    mdir = mt._current_models_dir()
    real = os.path.realpath(mdir) if mdir else ""
    res = mt._check_model_compatibility(mdir) if mdir else {"compatible": True, "reason": "kein current"}
    print(json.dumps({
        "dir": mdir or "",
        "real": real,
        "exists": bool(mdir and os.path.exists(mdir)),
        "compatible": bool(res.get("compatible", True)),
        "reason": res.get("reason", ""),
    }))
except Exception as exc:
    print(json.dumps({"dir": "", "real": "", "exists": False,
                      "compatible": True, "reason": f"check-skip: {exc}"}))
PYB123
)"
    _COMPAT_OK="$(printf '%s' "$_COMPAT_JSON"   | "$VENV/bin/python3" -c "import json,sys; print(json.load(sys.stdin).get('compatible'))" 2>/dev/null || echo True)"
    _COMPAT_DIR="$(printf '%s' "$_COMPAT_JSON"  | "$VENV/bin/python3" -c "import json,sys; print(json.load(sys.stdin).get('dir',''))" 2>/dev/null || echo '')"
    _COMPAT_REAL="$(printf '%s' "$_COMPAT_JSON" | "$VENV/bin/python3" -c "import json,sys; print(json.load(sys.stdin).get('real',''))" 2>/dev/null || echo '')"
    _COMPAT_EX="$(printf '%s' "$_COMPAT_JSON"   | "$VENV/bin/python3" -c "import json,sys; print(json.load(sys.stdin).get('exists'))" 2>/dev/null || echo False)"
    _COMPAT_RE="$(printf '%s' "$_COMPAT_JSON"   | "$VENV/bin/python3" -c "import json,sys; print(json.load(sys.stdin).get('reason',''))" 2>/dev/null || echo '')"

    if [[ "$_COMPAT_OK" == "True" ]]; then
        check_ok "ML-Modelle kompatibel zum aktuellen Feature-Schema (${_COMPAT_RE:-keine Modelle vorhanden})"
    else
        check_warn "B123: ML-Feature-Mismatch erkannt — ${_COMPAT_RE}"
        if [[ "$MODE" == "full" ]]; then
            # Full-Modus: inkompatible Modelle löschen (werden neu trainiert).
            # current ist i.d.R. ein Symlink auf v_<id> → realen Pfad löschen + Link entfernen.
            if [[ "$_COMPAT_EX" == "True" ]]; then
                if [[ -n "$_COMPAT_REAL" && -d "$_COMPAT_REAL" && "$_COMPAT_REAL" == "$TARGET"/train_data/models/* ]]; then
                    log_warn "[B123] Full-Modus: lösche inkompatible Modelle in $_COMPAT_REAL"
                    rm -rf "$_COMPAT_REAL"
                fi
                # Symlink/Verzeichnis 'current' entfernen
                rm -rf "$_COMPAT_DIR" 2>/dev/null || true
                check_ok "Inkompatible Modelle gelöscht — werden beim nächsten Training neu erstellt."
            else
                check_ok "Keine inkompatiblen Modelle vorhanden (Full-Modus hat sie bereits entfernt)."
            fi
        else
            # Upgrade-Modus: quarantänisieren (kein Löschen — user-generierte Lerndaten).
            log_warn "[B123] Upgrade-Modus: quarantänisiere inkompatiblen Modellstand (kein Löschen)."
            if ( cd "$TARGET" && "$VENV/bin/python3" -c "import model_training as mt; mt._quarantine_incompatible_current('install.sh B123: feature mismatch')" ) 2>/dev/null; then
                check_ok "Modelle quarantänisiert (current → current_incompatible_*). Runtime läuft kinematisch bis Retrain."
            else
                check_warn "B123: Quarantäne fehlgeschlagen — bitte manuell prüfen."
            fi
            note_manual "B123: ML-Feature-Mismatch — nach Datensammlung neu trainieren: cd $TARGET && source venv/bin/activate && python3 dataset_builder.py && python3 model_training.py"
        fi
    fi
else
    check_warn "B123: venv-Python fehlt — ML-Kompatibilitätsprüfung übersprungen."
fi

# ==============================================================================
# PHASE 9 — Tests (letzter Schritt, beide Modi)
# ==============================================================================
CURRENT_PHASE="Phase 9 — Tests"
log_step "Phase 9 — Tests ausführen"

# P-S02: Langzeitstatistik initialisieren (nur wenn noch keine Aggregate vorhanden).
if [ ! -f "${TARGET}/train_data/statistics/climatology_grid.json" ]; then
  log_info "P-S02 Backfill der Langzeitstatistik..."
  ( cd "${TARGET}" && python3 backfill_track_ends.py ) || log_warn "Backfill fehlgeschlagen (nicht kritisch)"
  ( cd "${TARGET}" && python3 -c "from stats_aggregator import aggregate; print(aggregate(reset=True))" ) \
    || log_warn "Erst-Aggregation fehlgeschlagen (nicht kritisch)"
fi

# Vorgabe Zieldefinition: Fehlgeschlagene Tests erzeugen AUSSCHLIESSLICH
# Warnungen und brechen die Installation NIEMALS ab. Es gibt bewusst keine
# Option für Hart-Abbruch — der Exit-Code dieser Phase ist immer 0.

_TESTS_DIR="$TARGET/tests"

if [[ ! -d "$_TESTS_DIR" ]] || ! ls "$_TESTS_DIR"/test_*.py >/dev/null 2>&1; then
    check_warn "Keine Tests gefunden in $_TESTS_DIR — Phase 9 übersprungen."
else
    # pytest sicherstellen (steht in requirements.txt auskommentiert → ggf. fehlend)
    if ! "$VENV/bin/python3" -c "import pytest" 2>/dev/null; then
        log_info "pytest nicht im venv — installiere nach..."
        if pip_install_safe pytest >/dev/null 2>&1; then
            check_ok "pytest nachinstalliert"
        else
            check_warn "pytest konnte nicht installiert werden — Tests übersprungen."
            note_manual "source $VENV/bin/activate && pip install pytest && cd $TARGET && python3 -m pytest"
        fi
    fi

    if "$VENV/bin/python3" -c "import pytest" 2>/dev/null; then
        log_info "Führe Test-Suite aus: $_TESTS_DIR"
        _TEST_LOG="$TARGET/train_data/evaluation/install_pytest.log"
        mkdir -p "$(dirname "$_TEST_LOG")"

        # Im Projektverzeichnis ausführen, damit pytest.ini + Imports greifen.
        # rootdir = $TARGET; -p no:cacheprovider vermeidet .pytest_cache-Schreibrechte-Probleme.
        set +e
        trap '' ERR        # B107: ERR-Trap temporär deaktivieren — set+e reicht nicht
        ( cd "$TARGET" && "$VENV/bin/python3" -m pytest tests \
              -p no:cacheprovider 2>&1 ) | tee "$_TEST_LOG"
        _PYTEST_RC=${PIPESTATUS[0]}
        trap on_error ERR  # ERR-Trap wiederherstellen
        set -e

        # Kurz-Zusammenfassung aus der letzten pytest-Zeile (passed/failed/...)
        _SUMMARY="$(grep -E '=+ .*(passed|failed|error|skipped).* =+' "$_TEST_LOG" | tail -1 | sed -E 's/=+//g; s/^ +//; s/ +$//' || true)"

        if [[ "$_PYTEST_RC" -eq 0 ]]; then
            check_ok "Tests bestanden: ${_SUMMARY:-alle Tests grün}"
        elif [[ "$_PYTEST_RC" -eq 5 ]]; then
            # pytest exit 5 = keine Tests gesammelt
            check_warn "pytest hat keine Tests gesammelt (Exit 5)."
        else
            # Nur Warnung — NIE Abbruch (Vorgabe Zieldefinition).
            check_warn "Tests fehlgeschlagen (Exit $_PYTEST_RC): ${_SUMMARY:-siehe $_TEST_LOG}"
            note_manual "Details: cat $_TEST_LOG   |   erneut: cd $TARGET && source venv/bin/activate && python3 -m pytest tests -v"
        fi
        log_info "Test-Protokoll gespeichert: $_TEST_LOG"
    fi
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

  5. Debug-Export-Timer prüfen:
       systemctl list-timers | grep wetterprojekt-debug-export-branch
       journalctl -u wetterprojekt-debug-export-branch.service -n 100 --no-pager

  6. Logs live:
       journalctl -fu wetterprojekt
NEXTSTEPS
