"""P95 — Modell-Dropdown + Ausfuehrzeitfelder in der Lokale-Analyse-Karte.

Prueft, dass Frontend und Backend die neuen Felder korrekt einbinden.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
JSX = REPO / "frontend" / "src" / "pages" / "AiSuggestions.jsx"
APP = REPO / "app.py"


def _jsx():
    return JSX.read_text(encoding="utf-8")


def _app():
    return APP.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Frontend
# --------------------------------------------------------------------------

def test_model_dropdown_in_local_analysis_card():
    t = _jsx()
    la_section = t.split("Lokale Analyse am Pi", 1)[1].split("HitL", 1)[0]
    assert "laCfg.model" in la_section, "Modell-Feld fehlt in der Lokale-Analyse-Karte"
    assert "CLI-Vorgabe" in la_section, "Default-Option fehlt"


def test_model_dropdown_uses_shared_models_list():
    """Die Modellliste wird schon beim Mount geladen (models-State) und muss
    im Dropdown wiederverwendet werden — kein zweiter Fetch."""
    la_section = _jsx().split("Lokale Analyse am Pi", 1)[1].split("HitL", 1)[0]
    assert "models.map" in la_section


def test_cron_fields_in_local_analysis_card():
    la_section = _jsx().split("Lokale Analyse am Pi", 1)[1].split("HitL", 1)[0]
    assert "laCfg.cron_hour" in la_section, "cron_hour-Feld fehlt"
    assert "laCfg.cron_minute" in la_section, "cron_minute-Feld fehlt"


def test_max_turns_label_updated():
    """B480/B484: Obergrenze jetzt 500, nicht mehr 200."""
    la_section = _jsx().split("Lokale Analyse am Pi", 1)[1].split("HitL", 1)[0]
    assert "1–500" in la_section or "1\u2013500" in la_section
    assert "1–200" not in la_section and "1\u2013200" not in la_section


# --------------------------------------------------------------------------
# Backend
# --------------------------------------------------------------------------

def test_backend_max_turns_validation_allows_500():
    t = _app()
    assert '("max_turns", 1, 500)' in t, "Backend validiert max_turns noch auf 200"
    assert '("max_turns", 1, 200)' not in t


def test_backend_accepts_model_field():
    """Das model-Feld muss im String-Validierungsblock stehen."""
    save_section = _app().split("api_local_analysis_config_save", 1)[1].split("@app.route", 1)[0]
    assert '"model"' in save_section


def test_backend_accepts_cron_fields():
    save_section = _app().split("api_local_analysis_config_save", 1)[1].split("@app.route", 1)[0]
    assert '"cron_hour"' in save_section
    assert '"cron_minute"' in save_section
