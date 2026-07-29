"""P89 — Prompt-Umbau: Primärmission Vorhersagequalität, Konsum von
ai_checks_results.json, 80%-Bremse entfernt. B481-Disziplin bleibt erhalten.
"""
from pathlib import Path

PROMPT = Path(__file__).resolve().parents[1] / "docs" / "LOCAL_ANALYSIS_PROMPT.md"


def _t():
    return PROMPT.read_text(encoding="utf-8")


def test_primary_mission_declared():
    t = _t()
    assert "Primärziel" in t and "Vorhersagequalität" in t


def test_consumes_ai_checks_results():
    t = _t()
    assert "ai_checks_results.json" in t
    assert "not_implemented" in t


def test_hard_80pct_stop_removed():
    t = _t()
    assert "80 %" not in t and "SOFORT STOPPEN" not in t


def test_b481_discipline_preserved():
    t = _t()
    assert "KEINE ZWISCHENLÖSUNG" in t and "kein Workaround" in t
    assert "KEINEN `prompts`-Eintrag" in t


def test_legacy_invariants_preserved():
    t = _t()
    assert "Schrittbudget" in t          # b471
    assert "tools/ro_query.py" in t      # b465
    for raw in ("journalctl -u", "sqlite3 -readonly", "`df -h`", "`free -m`"):
        assert raw not in t              # b465
    assert "code_ref=" in t and "beleg=" in t and "zusammenfassung" in t and "AIChecks.md" in t  # p77
