#!/bin/sh
# B476 — Ein einziger naechtlicher Ausloeser, zwei Betriebsarten. Laeuft als root
# (systemd) und startet je nach ANALYSIS_MODE genau einen gehaerteten Dienst:
#   local -> wetterprojekt-local-analysis.service (streng lesende Analyse am Pi)
#   sonst -> wetterprojekt-debug-export-branch.service (Export + Push nach GitHub)
set -u
REPO="${1:-/home/ki-pi/wetterprojekt}"
BASE="$REPO"
MODE="$("$REPO/venv/bin/python3" - "$REPO" <<'PYEOF'
import sys
repo = sys.argv[1]
sys.path.insert(0, repo)
try:
    from config import ANALYSIS_MODE as _default
    import runtime_config
    runtime_config.reload_overrides()
    print(str(runtime_config.get("ANALYSIS_MODE", _default) or "repo").strip().lower())
except Exception:
    print("repo")
PYEOF
)"
if [ "$MODE" = "local" ]; then
    # P98: Tuning-Verify (Ergebnis des vorherigen Tunings pruefen)
    if ! python3 "$BASE/tools/tuning_apply.py" --verify >>"$BASE/train_data/evaluation/tuning_dispatch.log" 2>&1; then
        echo "[DISPATCH] Verify fehlgeschlagen; Analyse/Apply abgebrochen" >&2
        exit 1
    fi

    systemctl start wetterprojekt-local-analysis.service
    STATUS="$BASE/train_data/evaluation/local_analysis_status.json"
    python3 - "$STATUS" <<'PYEOF'
import json, sys
status = json.load(open(sys.argv[1], encoding="utf-8"))
if status.get("state") != "ok" or not status.get("analysis_run_id"):
    raise SystemExit("aktueller Analyse-Lauf ist nicht erfolgreich gebunden")
PYEOF

    # P98: Tuning-Apply (neue Vorschlaege aus dem gerade abgeschlossenen Lauf anwenden)
    python3 "$BASE/tools/tuning_apply.py" --apply >>"$BASE/train_data/evaluation/tuning_dispatch.log" 2>&1
else
    exec systemctl start --no-block wetterprojekt-debug-export-branch.service
fi
