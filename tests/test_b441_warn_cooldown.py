"""B441: Persistenter, ortsbasierter Warn-Cooldown.

Der alte Schutz war an die cell_id gekoppelt (umgehbar) und nur im RAM (nicht
neustartfest). Alarme feuerten dadurch zu dicht — auch ohne Neustart, sobald eine Zelle
ihre cell_id wechselte.
"""
import importlib

import pytest


@pytest.fixture()
def wcd(tmp_path, monkeypatch):
    import warn_cooldown as m
    importlib.reload(m)
    monkeypatch.setattr(m, "_COOLDOWN_FILE", str(tmp_path / "warn_cooldown.json"))
    monkeypatch.setattr(m, "_default_cooldown_s", lambda: 900)
    return m


def test_frischer_ort_darf_warnen(wcd):
    assert wcd.filter_allowed(["Feldkirchen"]) == {"Feldkirchen"}
    assert wcd.is_blocked("Feldkirchen") is False


def test_nach_versand_gesperrt(wcd):
    wcd.mark_sent("Feldkirchen", now=1000.0)
    assert wcd.is_blocked("Feldkirchen", now=1000.0) is True
    assert wcd.filter_allowed(["Feldkirchen"], now=1300.0) == set()
    assert wcd.filter_allowed(["Feldkirchen"], now=1901.0) == {"Feldkirchen"}


def test_cooldown_ist_ortsbasiert_nicht_cellid(wcd):
    """Ein zweiter Alarm desselben Orts wird unabhängig von der cell_id unterdrückt."""
    wcd.mark_sent("Villach", now=1000.0)
    assert wcd.filter_allowed(["Villach"], now=1300.0) == set()


def test_persistent_ueber_reload(wcd, tmp_path, monkeypatch):
    """Der Zustand bleibt beim simulierten Neustart in der Datei erhalten."""
    wcd.mark_sent("Klagenfurt", now=1000.0)
    import warn_cooldown as m2
    importlib.reload(m2)
    monkeypatch.setattr(m2, "_COOLDOWN_FILE", str(tmp_path / "warn_cooldown.json"))
    monkeypatch.setattr(m2, "_default_cooldown_s", lambda: 900)
    assert m2.is_blocked("Klagenfurt", now=1300.0) is True


def test_mehrere_orte_unabhaengig(wcd):
    wcd.mark_sent("A", now=1000.0)
    result = wcd.filter_allowed(["A", "B"], now=1300.0)
    assert result == {"B"}


def test_defekte_datei_blockiert_nicht(wcd):
    from pathlib import Path
    Path(wcd._COOLDOWN_FILE).write_text("kein json", encoding="utf-8")
    assert wcd.filter_allowed(["X"]) == {"X"}


def test_main_ruft_cooldown_vor_versand():
    """main.py filtert _ready_to_warn vor dem E-Mail-Versand."""
    from pathlib import Path
    t = Path("main.py").read_text(encoding="utf-8")
    assert "import warn_cooldown" in t
    assert "filter_allowed(_ready_to_warn)" in t
    assert 'mark_sent(_loc_hit["name"])' in t
    i_filter = t.find("filter_allowed(_ready_to_warn)")
    i_send = t.find("from email_notifier import send_warning_email")
    assert 0 < i_filter < i_send
