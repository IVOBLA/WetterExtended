#!/bin/bash
# cleanup_radar_names.sh
# Einmaliger Fix: Umbenennen aller radar_TIMESTAMP.png → TIMESTAMP.png
# in train_data/radar/ (Trainingsarchiv) UND data/radar/ (Live-Serving-Verzeichnis,
# B266: zuvor nicht erfasst — siehe HAILO_INTEGRATION.md B265/B266).
# Doppelte (wo beide Varianten existieren) werden sicher behandelt.
# Ausführen: bash cleanup_radar_names.sh

SCRIPT_DIR="$(dirname "$0")"
RADAR_DIRS=(
    "$SCRIPT_DIR/train_data/radar"
    "$SCRIPT_DIR/data/radar"
)

total_renamed=0
total_duplicates=0

cleanup_dir() {
    local dir="$1"
    local renamed=0
    local duplicates=0
    local base ts target f

    echo "[INFO] Starte Radar-Dateinamen-Bereinigung in: $dir"

    if [ ! -d "$dir" ]; then
        echo "[SKIP] Verzeichnis nicht vorhanden: $dir"
        echo ""
        return
    fi

    for f in "$dir"/radar_*.png; do
        [ -f "$f" ] || continue
        base=$(basename "$f")
        ts="${base#radar_}"                          # radar_2026-05-19_10-22-00.png → 2026-05-19_10-22-00.png
        target="$dir/$ts"
        if [ -f "$target" ]; then
            echo "[SKIP-DUP] $base → $ts existiert bereits, lösche Duplikat mit Prefix"
            rm "$f"
            ((duplicates++))
        else
            mv "$f" "$target"
            echo "[RENAMED] $base → $ts"
            ((renamed++))
        fi
    done

    echo "[INFO] $dir: Umbenannt: $renamed | Duplikate entfernt: $duplicates"
    echo "[INFO] $dir: Verbleibende Dateien: $(ls "$dir"/*.png 2>/dev/null | wc -l)"
    echo ""

    total_renamed=$((total_renamed + renamed))
    total_duplicates=$((total_duplicates + duplicates))
}

for d in "${RADAR_DIRS[@]}"; do
    cleanup_dir "$d"
done

echo "[DONE] Gesamt — Umbenannt: $total_renamed | Duplikate entfernt: $total_duplicates"
