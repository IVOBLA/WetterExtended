#!/usr/bin/env bash
# backup_wetterprojekt.sh
# Sichert Modelle, Secrets und Konfiguration in ~/wetterprojekt-backup/<timestamp>/
# Aufgerufen wöchentlich vom Scheduler oder manuell via: bash backup_wetterprojekt.sh
#
# Gesichert: train_data/models/, .env, runtime_overrides.json,
#            locations.json, cell_filters.json
# NICHT gesichert: Trainingsdaten (zu groß), Frontend-Build (regenerierbar)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_ROOT="${BACKUP_DIR:-$HOME/wetterprojekt-backup}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
TS="$(date +%Y-%m-%d_%H%M%S)"
DEST="$BACKUP_ROOT/$TS"

mkdir -p "$DEST"

# ── Modelle sichern ────────────────────────────────────────────────────────
if [[ -d "$SCRIPT_DIR/train_data/models" ]]; then
    cp -r "$SCRIPT_DIR/train_data/models" "$DEST/"
    MODEL_COUNT=$(find "$DEST/models" -type f 2>/dev/null | wc -l)
    echo "[BACKUP] Modelle gesichert: $MODEL_COUNT Dateien"
else
    echo "[BACKUP] Warnung: train_data/models nicht gefunden"
fi

# ── Secrets + Konfiguration sichern ────────────────────────────────────────
for _f in \
    ".env" \
    "train_data/runtime_overrides.json" \
    "locations.json" \
    "train_data/cell_filters/cell_filters.json"; do
    _src="$SCRIPT_DIR/$_f"
    if [[ -f "$_src" ]]; then
        _dest_dir="$DEST/$(dirname "$_f")"
        mkdir -p "$_dest_dir"
        cp "$_src" "$_dest_dir/"
        echo "[BACKUP] Gesichert: $_f"
    fi
done

# ── Berechtigungen setzen (Secrets schützen) ─────────────────────────────
chmod 700 "$DEST"
[[ -f "$DEST/.env" ]] && chmod 600 "$DEST/.env"

# ── Größe berechnen ────────────────────────────────────────────────────────
DEST_SIZE=$(du -sh "$DEST" 2>/dev/null | cut -f1 || echo "?")

# ── Alte Backups löschen ──────────────────────────────────────────────────
DELETED=0
while IFS= read -r _old; do
    rm -rf "$_old"
    (( DELETED++ )) || true
done < <(find "$BACKUP_ROOT" -maxdepth 1 -mindepth 1 -type d -mtime +"$BACKUP_RETENTION_DAYS" 2>/dev/null)

# ── Zusammenfassung ────────────────────────────────────────────────────────
BACKUP_COUNT=$(find "$BACKUP_ROOT" -maxdepth 1 -mindepth 1 -type d 2>/dev/null | wc -l)
echo "[BACKUP] Abgeschlossen: $DEST ($DEST_SIZE)"
echo "[BACKUP] Gesamt: $BACKUP_COUNT Backup(s) in $BACKUP_ROOT | $DELETED alte gelöscht"
