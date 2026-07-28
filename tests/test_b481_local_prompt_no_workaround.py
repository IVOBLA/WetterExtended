"""B481 — Regression: Der lokale Analyse-Prompt muss saubere Endlösungen
erzwingen und Zwischenlösungen/Workarounds ausdrücklich verbieten.

Hintergrund: Ein lokaler Analyselauf schlug als Fix `except (ImportError,
OSError): pass` vor — eine Symptomunterdrückung, die einen echten .env-Rechte-
fehler bei den Produktionsdiensten still verdecken würde. Dieser Test stellt
sicher, dass die entsprechende Disziplin dauerhaft im Prompt verankert bleibt.
"""
from pathlib import Path

PROMPT = Path(__file__).resolve().parents[1] / "docs" / "LOCAL_ANALYSIS_PROMPT.md"


def _text() -> str:
    return PROMPT.read_text(encoding="utf-8")


def test_prompt_file_exists():
    assert PROMPT.is_file(), f"Prompt-Datei fehlt: {PROMPT}"


def test_forbids_zwischenloesung_explicitly():
    t = _text()
    assert "KEINE ZWISCHENLÖSUNG" in t
    assert "SAUBERE ENDLÖSUNG" in t
    assert "Workaround" in t
    assert "Symptomunterdrückung" in t


def test_forbids_broad_exception_swallowing_as_example():
    t = _text()
    # Das konkrete Anti-Muster muss als verbotenes Beispiel benannt sein.
    assert "except OSError: pass" in t or "except Exception" in t


def test_open_finding_without_workaround_allowed():
    t = _text()
    # Fehler ohne saubere Lösung: offener Befund statt Workaround-Prompt.
    assert "kein Workaround" in t
    assert "KEINEN `prompts`-Eintrag" in t


def test_prompts_output_rule_reinforces_clean_solution():
    t = _text()
    idx = t.find("- `prompts`:")
    assert idx != -1
    block = t[idx:idx + 400]
    assert "saubere Endlösung" in block
    assert "Zwischenlösung" in block or "Workaround" in block
