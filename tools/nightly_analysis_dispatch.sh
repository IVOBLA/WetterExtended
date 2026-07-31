#!/bin/sh
# B476 — Ein einziger naechtlicher Ausloeser, zwei Betriebsarten. Laeuft als root
# (systemd) und startet je nach ANALYSIS_MODE genau einen gehaerteten Dienst:
#   local -> wetterprojekt-local-analysis.service (streng lesende Analyse am Pi)
#   sonst -> wetterprojekt-debug-export-branch.service (Export + Push nach GitHub)
set -eu
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
    STATUS="$BASE/train_data/evaluation/local_analysis_status.json"
    RESULT="$BASE/train_data/evaluation/analysis_result.json"
    DISPATCH_STARTED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    OLD_IDS="$(python3 - "$STATUS" <<'PYEOF'
import json, pathlib, sys
try: d=json.loads(pathlib.Path(sys.argv[1]).read_text())
except Exception: d={}
print(str(d.get('analysis_run_id') or '')+'|'+str(d.get('result_id') or ''))
PYEOF
)"
    # P98: Tuning-Verify (Ergebnis des vorherigen Tunings pruefen)
    if ! python3 "$BASE/tools/tuning_apply.py" --verify >>"$BASE/train_data/evaluation/tuning_dispatch.log" 2>&1; then
        echo "[DISPATCH] Verify fehlgeschlagen; Analyse/Apply abgebrochen" >&2
        exit 1
    fi

    if ! systemctl start wetterprojekt-local-analysis.service; then
        echo "[DISPATCH] systemctl fehlgeschlagen; siehe: journalctl -u wetterprojekt-local-analysis.service" >>"$BASE/train_data/evaluation/tuning_dispatch.log"
        exit 1
    fi
    python3 - "$STATUS" "$RESULT" "$OLD_IDS" "$DISPATCH_STARTED" <<'PYEOF'
import json, sys
status = json.load(open(sys.argv[1], encoding="utf-8"))
result = json.load(open(sys.argv[2], encoding="utf-8"))
old_run, old_result = sys.argv[3].split("|", 1)
if status.get("state") != "ok" or not status.get("analysis_run_id") or not status.get("result_id"):
    raise SystemExit("aktueller Analyse-Lauf ist nicht erfolgreich gebunden")
if status["analysis_run_id"] == old_run or status["result_id"] == old_result:
    raise SystemExit("alter erfolgreicher Status darf nicht wiederverwendet werden")
if status.get("run_started_at_utc", "") < sys.argv[4]:
    raise SystemExit("Analyse begann vor Dispatcher")
for key in ("analysis_run_id", "result_id", "source_snapshot_id", "git_commit"):
    if result.get(key) != status.get(key): raise SystemExit("Ergebnisbindung stimmt nicht: "+key)
PYEOF

    # P98: Tuning-Apply (neue Vorschlaege aus dem gerade abgeschlossenen Lauf anwenden)
    python3 "$BASE/tools/tuning_apply.py" --apply >>"$BASE/train_data/evaluation/tuning_dispatch.log" 2>&1
else
    exec systemctl start --no-block wetterprojekt-debug-export-branch.service
fi
