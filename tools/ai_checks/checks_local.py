"""P83 — Deterministische Checks (Muster-Migration). Startet mit AC-080.

Weitere ACs werden in Folgeschritten (P8x) hierher migriert. Solange ein AC nicht
migriert ist, bleibt er 'not_implemented' und der LLM-Fallback im lokalen
Analyse-Prompt uebernimmt ihn.
"""
from __future__ import annotations

import json
from pathlib import Path

from tools.ai_checks import register

_STATUS_REL = "train_data/evaluation/local_analysis_status.json"
_LOG_REL = "train_data/evaluation/local_analysis_last_run.log"


def _read_json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


@register("AC-080")
def check_ac080_incomplete_step_budget(base) -> dict:
    """AC-080 — Lokaler Analyse-Lauf am Schrittbudget abgebrochen?

    Deterministisch: liest local_analysis_status.json; state=='incomplete' →
    Turn-/Zeitbudget erschoepft. Die Ein-/Mehrtagesabgrenzung (erwarteter
    Selbstschutz vs. dauerhafter Umfang) bleibt dem LLM ueberlassen — der
    Statusfile traegt nur den letzten Lauf.
    """
    st = _read_json(Path(base) / _STATUS_REL)
    if st is None:
        return {"status": "ok",
                "beleg": f"kein {_STATUS_REL} vorhanden (lokale Analyse ggf. nie gelaufen)",
                "detail": {"state": None}}
    state = str(st.get("state", ""))
    if state == "incomplete":
        return {
            "status": "finding",
            "beleg": f"state=incomplete; error={st.get('error')!r}; log={_LOG_REL}",
            "detail": {
                "state": state,
                "error": st.get("error"),
                "log_path": _LOG_REL,
                "hinweis": ("einmaliges incomplete = erwarteter Selbstschutz (kein Fehler); "
                            "mehrere Tage in Folge = Verbesserung: max_turns/timeout_s in "
                            "config.LOCAL_ANALYSIS_CONFIG anheben oder erledigte ACs nach "
                            "'## Erledigt' verschieben"),
            },
        }
    return {"status": "ok", "beleg": f"state={state or 'unbekannt'}", "detail": {"state": state}}
