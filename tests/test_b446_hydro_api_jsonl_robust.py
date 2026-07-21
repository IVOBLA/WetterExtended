"""B446: hydro_api-JSONL-Leser ignorieren Nicht-Objekt-Zeilen statt zu werfen.

KI-Report 2026-07-21: eine nackte Zahl-Zeile in einer hydro_impact_*.jsonl warf
'AttributeError: float object has no attribute get' (18× am 2026-07-20). B438 hatte
denselben Defekt in hydro_flood_ml.py behoben, diese drei hydro_api-Stellen nicht.
"""
import importlib

import pytest


@pytest.fixture()
def api(tmp_path, monkeypatch):
    import hydro_api as m
    importlib.reload(m)
    monkeypatch.setattr(m, "IMPACT_DIR", tmp_path)
    monkeypatch.setattr(m, "VERIFICATIONS", tmp_path / "hydro_verifications.jsonl")
    return m


def _write(path, lines):
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_all_impacts_ignoriert_nackte_zahl(api, tmp_path):
    _write(tmp_path / "hydro_impact_20260720.jsonl", [
        '{"event_id":"E1","station_id":"2001049","cell_id":"C1"}',
        '8.0',            # nackte Zahl → float
        'null',           # JSON null
        '[1,2,3]',        # Array
        '{"event_id":"E2","station_id":"2001050"}',
    ])
    rows = api.all_impacts()
    assert all(isinstance(r, dict) for r in rows)
    assert {r["event_id"] for r in rows} == {"E1", "E2"}


def test_latest_status_by_event_ueberspringt_nicht_dict(api, tmp_path):
    _write(tmp_path / "hydro_verifications.jsonl", [
        '{"event_id":"E1","cell_id":"C1","station_id":"S1"}',
        '3.14',
        '{"event_id":"E2"}',
    ])
    out = api._latest_status_by_event()
    assert "E1" in out and "E2" in out
    assert all(isinstance(v, dict) for v in out.values())


def test_normalized_impacts_wirft_nicht_bei_float(api, tmp_path, monkeypatch):
    _write(tmp_path / "hydro_impact_20260720.jsonl", [
        '{"event_id":"E1","station_id":"2001049","cell_id":"C1"}',
        '8.0',
    ])
    _write(tmp_path / "hydro_verifications.jsonl", [])
    monkeypatch.setattr(api, "_disabled_station_ids", lambda: set())
    result = api.normalized_impacts()
    assert isinstance(result, list)
    assert any(str(e.get("event_id")) == "E1" for e in result)


def test_leere_und_defekte_datei_kein_absturz(api, tmp_path, monkeypatch):
    _write(tmp_path / "hydro_impact_20260720.jsonl", ['42', 'true', '"string"'])
    _write(tmp_path / "hydro_verifications.jsonl", ['1.0'])
    monkeypatch.setattr(api, "_disabled_station_ids", lambda: set())
    assert api.all_impacts() == api.latest_impacts() or isinstance(api.all_impacts(), list)
    assert api._latest_status_by_event() == {}
    assert isinstance(api.normalized_impacts(), list)
