#!/bin/sh
# B476 — Ein einziger naechtlicher Ausloeser, zwei Betriebsarten. Laeuft als root
# (systemd) und startet je nach ANALYSIS_MODE genau einen gehaerteten Dienst:
#   local -> wetterprojekt-local-analysis.service (streng lesende Analyse am Pi)
#   sonst -> wetterprojekt-debug-export-branch.service (Export + Push nach GitHub)
set -u
REPO="${1:-/home/ki-pi/wetterprojekt}"
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
    exec systemctl start --no-block wetterprojekt-local-analysis.service
else
    exec systemctl start --no-block wetterprojekt-debug-export-branch.service
fi
