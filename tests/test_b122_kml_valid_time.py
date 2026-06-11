"""
B122 — Tests: echte Radar-Valid-Time aus KML <TimeStamp> / PNG-Name.

Abgedeckt:
  - <TimeStamp><when> wird korrekt nach Vienna-Lokalzeit umgerechnet
  - PNG-Dateiname-Fallback liefert dieselbe Zeit
  - Quellen-Priorität: TimeStamp vor PNG-Name vor Last-Modified
  - Fehlende KML → None (kein Crash)
"""
import importlib
import sys
import types

import pytest


# Echte ARSO-KML (07:15 CEST = 05:15 UTC)
_KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
   <GroundOverlay>
      <name>si0zm</name>
      <description>11.06.2026 07:15 CEST (2026-06-11T05:15:00Z)</description>
      <Icon><href>inca_si0zm_20260611-0515+0000.png</href></Icon>
      <TimeStamp><when>2026-06-11T05:15:00Z</when></TimeStamp>
   </GroundOverlay>
</kml>
"""

_KML_NO_TS = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
   <GroundOverlay>
      <Icon><href>inca_si0zm_20260611-0515+0000.png</href></Icon>
   </GroundOverlay>
</kml>
"""


def _rd(monkeypatch):
    """radar_download frisch importieren mit debug/requests-Stubs."""
    if "debug_utils" not in sys.modules:
        stub = types.ModuleType("debug_utils")
        stub.debug_log = lambda *a, **k: None
        stub.log_api_failure = lambda *a, **k: None
        stub.log_api_call = lambda *a, **k: None
        stub.log_http_response = lambda *a, **k: None
        monkeypatch.setitem(sys.modules, "debug_utils", stub)
    if "requests" not in sys.modules:
        rq = types.ModuleType("requests")
        rq.exceptions = types.SimpleNamespace(Timeout=TimeoutError, HTTPError=RuntimeError)
        rq.get = lambda *a, **k: None
        monkeypatch.setitem(sys.modules, "requests", rq)
    monkeypatch.delitem(sys.modules, "radar_download", raising=False)
    try:
        return importlib.import_module("radar_download")
    except Exception as exc:
        pytest.skip(f"radar_download nicht importierbar: {exc}")


def test_timestamp_from_kml_when(tmp_path, monkeypatch):
    rd = _rd(monkeypatch)
    kml_path = tmp_path / "latest.kml"
    kml_path.write_text(_KML, encoding="utf-8")
    monkeypatch.setattr(rd, "_LATEST_KML_FILE", str(kml_path))
    assert rd._acq_from_kml_timestamp() == "2026-06-11_07-15-00"


def test_timestamp_from_pngname(tmp_path, monkeypatch):
    rd = _rd(monkeypatch)
    kml_path = tmp_path / "latest.kml"
    kml_path.write_text(_KML_NO_TS, encoding="utf-8")
    monkeypatch.setattr(rd, "_LATEST_KML_FILE", str(kml_path))
    assert rd._acq_from_kml_timestamp() is None      # kein <when>
    assert rd._acq_from_kml_pngname() == "2026-06-11_07-15-00"


def test_priority_timestamp_wins(tmp_path, monkeypatch):
    """get_acquisition_timestamp bevorzugt KML-TimeStamp vor Last-Modified."""
    rd = _rd(monkeypatch)
    kml_path = tmp_path / "latest.kml"
    kml_path.write_text(_KML, encoding="utf-8")
    monkeypatch.setattr(rd, "_LATEST_KML_FILE", str(kml_path))
    # Last-Modified absichtlich abweichend setzen
    monkeypatch.setattr(rd, "_read_last_modified", lambda: "Wed, 11 Jun 2026 05:30:00 GMT")
    assert rd.get_acquisition_timestamp() == "2026-06-11_07-15-00"


def test_fallback_to_last_modified(tmp_path, monkeypatch):
    """Ohne KML → Last-Modified-Fallback greift."""
    rd = _rd(monkeypatch)
    monkeypatch.setattr(rd, "_LATEST_KML_FILE", str(tmp_path / "nonexistent.kml"))
    monkeypatch.setattr(rd, "_read_last_modified", lambda: "Wed, 11 Jun 2026 05:15:00 GMT")
    # 05:15 UTC → 07:15 Vienna
    assert rd.get_acquisition_timestamp() == "2026-06-11_07-15-00"


def test_missing_everything_returns_none(tmp_path, monkeypatch):
    rd = _rd(monkeypatch)
    monkeypatch.setattr(rd, "_LATEST_KML_FILE", str(tmp_path / "nope.kml"))
    monkeypatch.setattr(rd, "_read_last_modified", lambda: None)
    assert rd.get_acquisition_timestamp() is None
