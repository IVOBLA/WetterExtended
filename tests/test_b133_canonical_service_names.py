"""B133: Logger-Service-Namen == Cache-Namespace == Registry (kanonisch).

Verhindert dauerhafte 0-Zeilen + fehlende Zeitstempel im Dashboard durch
Namens-Mismatch zwischen api_call_counts-Logger und _KNOWN_EXTERNAL_SERVICES.
"""
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _src(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def test_blitz_logger_canonical():
    s = _src("blitz_api.py")
    assert '"blitzortung_last_strikes"' in s
    # exakt-quotierter alter Name darf nicht mehr vorkommen
    assert not re.search(r'"blitzortung"(?!_| :| )', s)  # "blitzortung" als ganzes Token
    assert '"blitzortung"' not in s
    assert '"blitzortung:last_strikes"' in s  # cache_key unverändert


def test_tawes_logger_canonical():
    s = _src("fetch_tawes_gust.py")
    assert '"geosphere_tawes"' not in s
    assert '"geosphere_tawes_all"' in s
    assert '"geosphere:tawes_all"' in s  # cache_key unverändert


def test_eumetview_caps_logger_canonical():
    s = _src("cloud_height_from_eumetview.py")
    assert '"eumetview_wms_caps"' not in s
    assert '"eumetview_capabilities"' in s
    assert '"eumetview_wms"' in s            # TIFF-Operation bleibt
    assert '"eumetview:capabilities"' in s   # cache_key unverändert


def test_registry_cleaned():
    pytest.importorskip("flask")
    import app as app_module
    reg = set(app_module._KNOWN_EXTERNAL_SERVICES)
    assert "openmeteo_outlook" in reg
    assert "eumetview_wms" in reg
    assert "open_meteo_outlook" not in reg
    assert "open_meteo_atmosphere" not in reg
    # kanonische Namespaces weiterhin enthalten
    for canon in ("blitzortung_last_strikes", "geosphere_tawes_all",
                  "eumetview_capabilities", "geosphere_cape"):
        assert canon in reg
