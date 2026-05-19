#!/bin/bash
# cleanup_radar_names.sh
# Einmaliger Fix: Umbenennen aller radar_TIMESTAMP.png → TIMESTAMP.png in train_data/radar/
# Doppelte (wo beide Varianten existieren) werden sicher behandelt.
# Ausführen: bash cleanup_radar_names.sh

RADAR_DIR="$(dirname "$0")/train_data/radar"

echo "[INFO] Starte Radar-Dateinamen-Bereinigung in: $RADAR_DIR"

renamed=0
skipped=0
duplicates=0

for f in "$RADAR_DIR"/radar_*.png; do
    [ -f "$f" ] || continue
    base=$(basename "$f")
    ts="${base#radar_}"                          # radar_2026-05-19_10-22-00.png → 2026-05-19_10-22-00.png
    target="$RADAR_DIR/$ts"
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

echo ""
echo "[DONE] Umbenannt: $renamed | Duplikate entfernt: $duplicates | Übersprungen: $skipped"
echo "[INFO] Verbleibende Dateien: $(ls "$RADAR_DIR"/*.png 2>/dev/null | wc -l)"
