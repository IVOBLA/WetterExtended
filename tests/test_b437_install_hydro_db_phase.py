"""B437: install.sh prüft und repariert die Hydro-Sample-DB.

Der Testkörper validiert die eingefügte Phase strukturell (die Bash-Logik selbst läuft
im Deploy). Verhindert wird v.a., dass die Phase versehentlich im full-Modus repariert
(dort gibt es keine Alt-DB) oder ohne Service-Stopp gegen laufende Leser arbeitet.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

INSTALL = Path("install.sh")


def _txt():
    return INSTALL.read_text(encoding="utf-8")


def test_phase_existiert_und_steht_vor_phase_9():
    t = _txt()
    i895 = t.find("Phase 8.95 — Hydro-DB-Integrität")
    i9 = t.find('CURRENT_PHASE="Phase 9 — Tests"')
    assert i895 != -1, "Phase 8.95 fehlt"
    assert i9 != -1, "Phase 9 fehlt"
    assert i895 < i9, "Phase 8.95 muss vor Phase 9 stehen"


def test_full_modus_repariert_nicht():
    """Im full-Modus wurde train_data gelöscht — keine Reparatur, nur Hinweis."""
    t = _txt()
    block = t[t.find("Phase 8.95 — Hydro-DB-Integrität"):t.find('CURRENT_PHASE="Phase 9 — Tests"')]
    full_branch = block[block.find('if [[ "$MODE" == "full" ]]'):block.find("elif")]
    assert "repair_sample_db" not in full_branch


def test_reparatur_stoppt_services_vorher():
    t = _txt()
    block = t[t.find("Phase 8.95 — Hydro-DB-Integrität"):t.find('CURRENT_PHASE="Phase 9 — Tests"')]
    corrupt = block[block.find('"$_INT_STATUS" == "corrupt"'):]
    stop_pos = corrupt.find("systemctl stop")
    repair_pos = corrupt.find("repair_sample_db")
    start_pos = corrupt.find("systemctl start")
    assert 0 < stop_pos < repair_pos < start_pos, \
        "Reihenfolge muss sein: Services stoppen → reparieren → starten"


def test_sicherung_vor_reparatur():
    t = _txt()
    block = t[t.find("Phase 8.95 — Hydro-DB-Integrität"):t.find('CURRENT_PHASE="Phase 9 — Tests"')]
    assert "pre_b437" in block, "Keine forensische Sicherung vor der Reparatur"
    cp_pos = block.find("cp -a")
    repair_pos = block.find("repair_sample_db")
    assert 0 < cp_pos < repair_pos, "Sicherung muss vor der Reparatur erfolgen"


def test_datenverlust_wird_als_manueller_hinweis_gemeldet():
    t = _txt()
    assert "endgültig verloren" in t
    assert re.search(r'_REP_SKIPPED.*!=\s*"0"', t), "rows_skipped>0 muss gemeldet werden"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash nicht verfügbar")
def test_bash_syntax_gueltig():
    res = subprocess.run(["bash", "-n", str(INSTALL)], capture_output=True, text=True)
    assert res.returncode == 0, f"install.sh Syntaxfehler: {res.stderr}"
