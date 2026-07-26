"""B472 — AIChecks.md enthaelt nur noch Jedes-Mal-Pruefungen."""
import re
from pathlib import Path

AICHECKS = Path(__file__).resolve().parents[1] / "AIChecks.md"
GELOESCHT = ["AC-011","AC-012","AC-016","AC-021","AC-039","AC-040","AC-041","AC-052","AC-053"]
ARCHIVIERT = ["AC-001","AC-002","AC-003","AC-005","AC-006","AC-008","AC-009","AC-015",
              "AC-032","AC-034","AC-035","AC-051","AC-054","AC-055","AC-056"]


def _offen_ids():
    text = AICHECKS.read_text(encoding="utf-8")
    offen = text.partition("\n## Erledigt\n")[0]
    return set(re.findall(r"(?m)^### (AC-\d+)", offen))


def test_werkzeug_disziplin_vollstaendig_entfernt():
    text = AICHECKS.read_text(encoding="utf-8")
    for i in GELOESCHT:
        assert f"### {i} " not in text, f"{i} haette entfernt sein muessen"


def test_einmalpruefungen_nicht_mehr_offen():
    offen = _offen_ids()
    for i in ARCHIVIERT:
        assert i not in offen, f"{i} steht noch in ## Offen"


def test_archivierte_stehen_unter_erledigt():
    erledigt = AICHECKS.read_text(encoding="utf-8").partition("\n## Erledigt\n")[2]
    for i in ARCHIVIERT:
        assert i in erledigt, f"{i} fehlt in ## Erledigt"
