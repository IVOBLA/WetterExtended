"""P93 — AC-080 korrigiert: alle Nicht-ok-Zustaende melden.

Testet die deterministische Pruefung check_ac080_incomplete_step_budget gegen
alle sieben Zustaende, die run_local_analysis.py schreiben kann, plus
Grenzfaelle (kein File, leerer state, unbekannter state).
"""
import json
from pathlib import Path

from tools.ai_checks.checks_local import check_ac080_incomplete_step_budget as chk


def _write(tmp_path, state, **extra):
    ev = tmp_path / "train_data" / "evaluation"
    ev.mkdir(parents=True, exist_ok=True)
    data = {"state": state}
    data.update(extra)
    (ev / "local_analysis_status.json").write_text(
        json.dumps(data), encoding="utf-8")


# --------------------------------------------------------------------------
# ok-Zustaende → status == "ok"
# --------------------------------------------------------------------------

def test_state_ok(tmp_path):
    _write(tmp_path, "ok")
    r = chk(tmp_path)
    assert r["status"] == "ok"
    assert r["detail"]["state"] == "ok"


def test_state_mode_repo(tmp_path):
    _write(tmp_path, "mode_repo")
    r = chk(tmp_path)
    assert r["status"] == "ok"
    assert r["detail"]["state"] == "mode_repo"


def test_state_mode_changed_today(tmp_path):
    _write(tmp_path, "mode_changed_today")
    r = chk(tmp_path)
    assert r["status"] == "ok"


def test_state_max_attempts_reached(tmp_path):
    _write(tmp_path, "max_attempts_reached")
    r = chk(tmp_path)
    assert r["status"] == "ok"


def test_no_status_file(tmp_path):
    r = chk(tmp_path)
    assert r["status"] == "ok"
    assert r["detail"]["state"] is None


# --------------------------------------------------------------------------
# Finding-Zustaende → status == "finding"
# --------------------------------------------------------------------------

def test_state_incomplete(tmp_path):
    _write(tmp_path, "incomplete", error="Schritt-Limit erreicht")
    r = chk(tmp_path)
    assert r["status"] == "finding"
    assert "incomplete" in r["beleg"]
    assert r["detail"]["state"] == "incomplete"
    assert r["detail"]["error"] == "Schritt-Limit erreicht"


def test_state_failed_with_rc(tmp_path):
    """B U G F I X  P93: 'failed' wurde vor P93 als 'ok' gemeldet."""
    _write(tmp_path, "failed", error="Zeitlimit 900s ueberschritten", rc=124)
    r = chk(tmp_path)
    assert r["status"] == "finding", \
        f"'failed' muss ein Finding sein, nicht '{r['status']}'"
    assert "failed" in r["beleg"]
    assert r["detail"]["state"] == "failed"
    assert r["detail"]["rc"] == 124


def test_state_failed_rc_zero_bad_payload(tmp_path):
    """failed mit rc=0 (Antwort unbrauchbar) — ebenfalls Finding."""
    _write(tmp_path, "failed", error="Antwort unbrauchbar: kein JSON", rc=0)
    r = chk(tmp_path)
    assert r["status"] == "finding"
    assert r["detail"]["state"] == "failed"
    assert r["detail"]["rc"] == 0


def test_state_precondition_failed(tmp_path):
    """B U G F I X  P93: 'precondition_failed' wurde vor P93 als 'ok' gemeldet."""
    _write(tmp_path, "precondition_failed",
           error="Claude-CLI nicht gefunden")
    r = chk(tmp_path)
    assert r["status"] == "finding", \
        f"'precondition_failed' muss ein Finding sein, nicht '{r['status']}'"
    assert "precondition_failed" in r["beleg"]
    assert r["detail"]["state"] == "precondition_failed"


def test_unknown_state_is_finding(tmp_path):
    """Ein komplett unbekannter Zustand darf nicht als 'ok' durchrutschen."""
    _write(tmp_path, "neue_version_xyz", error="test")
    r = chk(tmp_path)
    assert r["status"] == "finding"
    assert "unbekannt" in r["detail"].get("hinweis", "").lower()


def test_empty_state_is_finding(tmp_path):
    """Leerer state (Korruptionsfall) darf nicht als 'ok' durchrutschen."""
    _write(tmp_path, "")
    r = chk(tmp_path)
    assert r["status"] == "finding"


# --------------------------------------------------------------------------
# Regression: P83-Importe bleiben intakt
# --------------------------------------------------------------------------

def test_function_is_importable():
    """Funktionsname muss stabil bleiben (P83-Test importiert ihn namentlich)."""
    from tools.ai_checks.checks_local import check_ac080_incomplete_step_budget
    assert callable(check_ac080_incomplete_step_budget)


def test_function_is_registered():
    from tools.ai_checks import CHECKS
    from tools.ai_checks.checks_local import check_ac080_incomplete_step_budget  # noqa: F401
    assert "AC-080" in CHECKS
