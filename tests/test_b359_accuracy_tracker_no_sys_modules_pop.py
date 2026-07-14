"""B359: Regressionsschutz — keine der Testdateien darf accuracy_tracker mehr
per sys.modules.pop() aus dem Modul-Cache werfen (verwaist app.py's bereits
gebundene Referenzen auf evaluate_all/load_history fuer den Rest der
Session, siehe B355-Testfehler-Analyse)."""
import sys

import pytest


_AFFECTED_FILES = [
    "tests/test_b296_nn_threshold_and_median.py",
    "tests/test_b335_accuracy_tracker_verified_zero_none.py",
    "tests/test_accuracy_tracker_horizon_mode.py",
    "tests/test_c1_dashboard_forecast_mode.py",
]


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_no_file_pops_accuracy_tracker_from_sys_modules():
    offenders = []
    for path in _AFFECTED_FILES:
        src = _read(path)
        if 'sys.modules.pop("accuracy_tracker"' in src or "sys.modules.pop('accuracy_tracker'" in src:
            offenders.append(path)
    assert not offenders, f"sys.modules.pop('accuracy_tracker') wieder eingefuehrt in: {offenders}"


def test_accuracy_tracker_module_identity_stable_across_import(monkeypatch, tmp_path):
    """Simuliert das B355-Szenario: nachdem eine der betroffenen Testdateien
    accuracy_tracker importiert und patcht, muss app.py's bereits gebundene
    Funktionsreferenz weiterhin auf DASSELBE Modul-Objekt zeigen."""
    pytest.importorskip("flask")
    import accuracy_tracker as at_before

    # Falls app.py in derselben Session bereits mit alten Referenzen importiert
    # wurde, wird nur app.py frisch gebunden; accuracy_tracker bleibt im
    # Modul-Cache stabil und wird gerade NICHT entfernt.
    sys.modules.pop("app", None)
    import app as app_module

    ev = tmp_path / "evaluation"
    ev.mkdir()
    monkeypatch.setattr(at_before, "HISTORY_FILE", str(ev / "accuracy_history.jsonl"), raising=False)

    # app_module.load_history wurde ueber "from accuracy_tracker import load_history"
    # gebunden -- __globals__ MUSS auf dasselbe Modul-Dict zeigen wie at_before.
    assert app_module.load_history.__globals__ is at_before.__dict__
    assert sys.modules.get("accuracy_tracker") is at_before
