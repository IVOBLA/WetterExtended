"""B443: Cooldown-unterdrückte, weiterhin aktive Orte bleiben warn-berechtigt.

Codex-Review zu B441: Ein unterdrückter Treffer fiel aus _ready_to_warn und wurde am
Frame-Ende als bekannt markiert — danach kein neuer Treffer mehr, keine Warnung bis zum
vollständigen Freiwerden + Wiedereintritt. Bei quasi-stationärer Zelle über einem Ort
verstummte die Warnung nach dem ersten Cooldown-Fenster.
"""
from pathlib import Path

MAIN = Path("main.py").read_text(encoding="utf-8")


def test_retry_set_deklariert():
    assert "_cooldown_retry: set = set()" in MAIN


def test_unterdrueckte_orte_werden_vorgemerkt():
    gate = MAIN[MAIN.find("import warn_cooldown as _wcd"):MAIN.find("Cooldown-Prüfung fehlgeschlagen")]
    assert "_cooldown_retry.add(_sname)" in gate, \
        "Unterdrückte Orte werden nicht für Retry vorgemerkt."


def test_retry_set_wird_auf_aktive_treffer_beschraenkt():
    assert "_cooldown_retry &= _current_hit_names" in MAIN, \
        "Retry-Set wird nicht auf noch getroffene Orte beschränkt — würde ewig wachsen."


def test_retry_orte_werden_wieder_kandidaten():
    assert "_cooldown_retry_active" in MAIN
    assert "_ready_to_warn.add(_lname)" in MAIN


def test_nach_warnung_aus_retry_entfernt():
    assert '_cooldown_retry.discard(_loc_hit["name"])' in MAIN, \
        "Erfolgreich gewarnte Orte bleiben im Retry-Set."


def test_reihenfolge_retry_vor_versand():
    """Retry-Reaktivierung muss vor dem Versandblock stehen."""
    i_retry = MAIN.find("_cooldown_retry_active = set(_cooldown_retry)")
    i_send = MAIN.find("from email_notifier import send_warning_email")
    assert 0 < i_retry < i_send


def test_syntax_ok():
    import ast
    ast.parse(MAIN)
