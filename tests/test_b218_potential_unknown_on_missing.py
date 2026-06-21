"""B218: _gewitterpotenzial liefert 'unbekannt' wenn LI UND CAPE fehlen,
statt fälschlich 'niedrig' (ruhiges Wetter)."""
import sys
import types

import pytest


def _import_mod():
    sys.modules.setdefault(
        "requests",
        types.SimpleNamespace(
            exceptions=types.SimpleNamespace(Timeout=TimeoutError, HTTPError=Exception),
            get=lambda *a, **k: None,
        ),
    )
    return pytest.importorskip("fetch_atmospheric_snapshot")


def test_unknown_when_li_and_cape_missing():
    mod = _import_mod()
    # li=0.0 (Default bei Ausfall), beide Flags gesetzt -> unbekannt
    assert mod._gewitterpotenzial(0.0, li_missing=1, cape_missing=1) == "unbekannt"


def test_high_when_li_unstable_and_present():
    mod = _import_mod()
    assert mod._gewitterpotenzial(-5.0, li_missing=0, cape_missing=0) == "hoch"


def test_low_only_when_data_present():
    mod = _import_mod()
    assert mod._gewitterpotenzial(1.0, li_missing=0, cape_missing=0) == "niedrig"


def test_partial_missing_keeps_classic_logic():
    mod = _import_mod()
    # nur CAPE fehlt, LI real instabil -> weiterhin hoch (kein 'unbekannt')
    assert mod._gewitterpotenzial(-5.0, li_missing=0, cape_missing=1) == "hoch"


def test_default_args_backward_compatible():
    mod = _import_mod()
    # ohne Flags (Defaults 0) verhält sich die Funktion wie vor B218
    assert mod._gewitterpotenzial(-2.0) == "mäßig"
    assert mod._gewitterpotenzial(0.5) == "niedrig"
