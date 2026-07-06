"""
B310: Diagnose-Instrumentierung fuer IR->Radar-Matching. Schreibt aggregierte
Zaehler (Kandidaten, Decisions, Reject-Reasons) nach jedem select_ir_radar_matches()-
Aufruf, um die Root-Cause der beobachteten 0%-Match-Rate (2525/2525 negative
Labels im Bestand) offline analysierbar zu machen. Keine Einzel-Kandidaten-Details,
nur Aggregate.

Hinweis: Falls tests/test_1l2_ir_radar_score_matching.py eigene _radar()/_ir()-Test-
Helper definiert, DIESE bevorzugt verwenden statt der hier lokal definierten Kopie.
"""
import json
import sys

from tests.test_1l2_ir_radar_score_matching import _ir, _radar


def _lineage(monkeypatch, tmp_path):
    import runtime_config
    sys.modules.pop("cell_lineage", None)
    monkeypatch.setattr(runtime_config, "get", lambda name, default=None: {
        "CELL_LINEAGE_STATE_DIR": str(tmp_path / "cell_lineage"),
        "CELL_LINEAGE_STATE_FILE": "cell_lineage_state.json",
        "CELL_LINEAGE_EVENTS_FILE": "cell_lineage_events.jsonl",
        "CELL_ID_PREFIX": "WX",
    }.get(name, default))
    import cell_lineage
    return cell_lineage


def test_diagnostics_file_written_after_select_matches(monkeypatch, tmp_path):
    mod = _lineage(monkeypatch, tmp_path)
    mod.select_ir_radar_matches([_radar()], [_ir()], timestamp="2026-07-05_12-00-00")
    diag_path = tmp_path / "cell_lineage" / "ir_radar_match_diagnostics.jsonl"
    assert diag_path.exists()
    rows = [json.loads(l) for l in diag_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["radar_object_count"] == 1
    assert rows[0]["ir_track_count"] == 1
    assert "decision_counts" in rows[0]
    assert "reason_counts" in rows[0]


def test_diagnostics_excludes_radar_objects_with_real_cell_id(monkeypatch, tmp_path):
    mod = _lineage(monkeypatch, tmp_path)
    mod.select_ir_radar_matches([_radar(cell_id="WX-20260705-0001")], [_ir()], timestamp="2026-07-05_12-00-00")
    diag_path = tmp_path / "cell_lineage" / "ir_radar_match_diagnostics.jsonl"
    rows = [json.loads(l) for l in diag_path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["radar_eligible_count"] == 0


def test_diagnostics_disabled_via_runtime_config(monkeypatch, tmp_path):
    import runtime_config
    sys.modules.pop("cell_lineage", None)
    monkeypatch.setattr(runtime_config, "get", lambda name, default=None: {
        "CELL_LINEAGE_STATE_DIR": str(tmp_path / "cell_lineage"),
        "CELL_ID_PREFIX": "WX",
        "IR_RADAR_MATCH_DIAGNOSTICS_ENABLED": False,
    }.get(name, default))
    import cell_lineage as mod
    mod.select_ir_radar_matches([_radar()], [_ir()], timestamp="2026-07-05_12-00-00")
    diag_path = tmp_path / "cell_lineage" / "ir_radar_match_diagnostics.jsonl"
    assert not diag_path.exists()


def test_diagnostics_never_raises_on_write_error(monkeypatch, tmp_path):
    mod = _lineage(monkeypatch, tmp_path)

    def _boom():
        raise OSError("boom")

    monkeypatch.setattr(mod, "_match_diagnostics_path", _boom)
    # Darf keine Exception werfen, auch wenn das Schreiben fehlschlaegt.
    selected, info = mod.select_ir_radar_matches([_radar()], [_ir()], timestamp="2026-07-05_12-00-00")
    assert isinstance(selected, list)
