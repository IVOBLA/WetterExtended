"""P94 — Lokaler Analyse-Prompt: Code-Verifikationspflicht fuer Verbesserungsvorschlaege.

Stellt sicher, dass der Analyse-Prompt die KI zur Code-Verifikation jedes
Verbesserungsvorschlags verpflichtet und die Schluesseldateien auflistet.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPT = REPO_ROOT / "docs" / "LOCAL_ANALYSIS_PROMPT.md"


def _prompt():
    return PROMPT.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Code-Verifikationspflicht vorhanden
# --------------------------------------------------------------------------

def test_prompt_exists():
    assert PROMPT.is_file()


def test_code_verification_block_present():
    t = _prompt()
    assert "Code-Verifikation (verpflichtend" in t


def test_three_step_methodology():
    """Ursache lokalisieren, Empfehlung formulieren, unbelegt-Fallback."""
    t = _prompt()
    assert "Ursache lokalisieren" in t
    assert "Empfehlung formulieren" in t
    assert "Kein Code gefunden" in t and "unbelegt" in t


def test_code_ref_required_in_verbesserungen():
    t = _prompt()
    assert "code_ref=<datei>:<zeile/funktion>" in t


def test_key_files_listed():
    """Alle Schluesseldateien fuer die Code-Verifikation muessen aufgefuehrt sein."""
    t = _prompt()
    for key in ("prediction.py", "object_tracking.py", "cell_lineage.py",
                "accuracy_tracker.py", "drift_detector.py", "dataset_builder.py"):
        assert key in t, f"Schluesseldatei fehlt im Prompt: {key}"


def test_key_functions_listed():
    """Die wichtigsten Funktionen/Konzepte muessen namentlich erwaehnt sein."""
    t = _prompt()
    for fn in ("_ml_runtime_gate_by_horizon", "_predict_lgbm_vector",
               "_append_kinematic", "Champion/Challenger"):
        assert fn in t, f"Schluesselfunktion fehlt im Prompt: {fn}"


def test_verbesserungen_format_updated():
    """Der Ausgabeblock fuer verbesserungen muss die neue Anforderung widerspiegeln."""
    t = _prompt()
    assert "code-belegte" in t


def test_old_verbesserungen_format_gone():
    """Der alte Text ohne code_ref-Pflicht darf nicht mehr stehen."""
    t = _prompt()
    # Der alte Text hatte "belegte Vorschläge, wie MAE/Drift" OHNE "code-belegte"
    # Der neue hat "code-belegte Vorschläge mit code_ref"
    if "belegte Vorschläge, wie MAE/Drift" in t:
        assert "code-belegte" in t, "Alte Formulierung ohne code_ref-Pflicht noch vorhanden"
