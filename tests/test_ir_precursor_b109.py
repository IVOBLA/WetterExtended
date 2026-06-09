"""B109: IR-Precursor-Flag wird korrekt persistiert nach Radar-Matching."""
import sys
import types

import pytest

sys.modules.setdefault(
    "debug_utils",
    types.SimpleNamespace(debug_log=lambda *a, **k: None),
)


def _get_module():
    return pytest.importorskip("ir_cell_tracking")


def test_b109_mark_radar_matched_clears_precursor(monkeypatch):
    """Radar-gematchter Track muss nach mark_radar_matched_tracks persistiert ir_only_precursor=0.0 haben."""
    mod = _get_module()
    fake_track = {"ir_id": "IR-001", "ir_only_precursor": 1.0, "radar_matched": False}
    state = {"tracks": {"ir_0": fake_track}, "next_id": 1}
    saved = []
    monkeypatch.setattr(mod, "_load_state", lambda: state)
    monkeypatch.setattr(mod, "_save_state", lambda new_state: saved.append(new_state))

    mod.mark_radar_matched_tracks(["IR-001"])

    assert fake_track["ir_only_precursor"] == 0.0
    assert fake_track.get("radar_matched") is True
    assert len(saved) == 1, "State muss nach mark_radar_matched_tracks persistiert werden"
    assert saved[0]["tracks"]["ir_0"] is fake_track


def test_b109_unmatched_track_keeps_precursor_score(monkeypatch):
    """Nicht-gematchter Track behält seinen ir_only_precursor."""
    mod = _get_module()
    fake_track = {"ir_id": "IR-002", "ir_only_precursor": 0.8}
    state = {"tracks": {"ir_0": fake_track}, "next_id": 1}
    saved = []
    monkeypatch.setattr(mod, "_load_state", lambda: state)
    monkeypatch.setattr(mod, "_save_state", lambda new_state: saved.append(new_state))

    mod.mark_radar_matched_tracks(["IR-999"])

    assert fake_track["ir_only_precursor"] == 0.8
    assert len(saved) == 0, "Kein Save bei keinem Match"


def test_b109_empty_list_no_save(monkeypatch):
    """Leere matched_ir_ids → kein State-Write."""
    mod = _get_module()
    saved = []
    monkeypatch.setattr(mod, "_load_state", lambda: pytest.fail("_load_state darf nicht aufgerufen werden"))
    monkeypatch.setattr(mod, "_save_state", lambda new_state: saved.append(new_state))

    mod.mark_radar_matched_tracks([])
    assert len(saved) == 0
