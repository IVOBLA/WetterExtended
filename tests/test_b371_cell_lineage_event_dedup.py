"""B371: Merge/Split-Ereignisse duerfen pro Konstellation nur EINMAL geschrieben werden."""
import json

import pytest

import cell_lineage as cl


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """Testisolation: State-Verzeichnis in tmp_path, kein sys.modules-Stub.

    Muster identisch zu tests/test_config_override_guard.py (monkeypatch + autouse),
    damit keine Modulkontamination zwischen Testdateien entsteht (vgl. B96/B160/B161/
    B334/B338/B364).
    """
    state_dir = tmp_path / "cell_lineage"
    state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(cl, "_state_dir", lambda: state_dir)
    yield state_dir


def _events(state_dir):
    path = state_dir / "cell_lineage_events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _merge_obj(cell_id="C1", track="T1"):
    return {"cell_id": cell_id, "id": track, "parents": ["T1", "T2"], "core_ratio": 0.5, "area": 100.0}


def test_repeated_merge_same_constellation_writes_single_event(_isolate_state):
    """10 Folgeframes mit identischer Parent-Konstellation -> genau 1 Event."""
    state = {}
    for _ in range(10):
        cl.record_cell_merge(["C1", "C2"], _merge_obj(), timestamp="2026-07-14_15-20-00", state=state)
    events = _events(_isolate_state)
    merges = [e for e in events if e.get("event_type") == "cell_merge"]
    assert len(merges) == 1, f"Erwartet 1 Merge-Event, geschrieben: {len(merges)}"


def test_first_merge_returns_event_followups_return_none(_isolate_state):
    state = {}
    first = cl.record_cell_merge(["C1", "C2"], _merge_obj(), timestamp="2026-07-14_15-20-00", state=state)
    second = cl.record_cell_merge(["C1", "C2"], _merge_obj(), timestamp="2026-07-14_15-25-00", state=state)
    assert first is not None and first.get("event_signature")
    assert second is None, "Folgeframe darf kein neues Event erzeugen"


def test_different_constellation_creates_new_event(_isolate_state):
    """Neue Parent-Menge = echtes neues Ereignis."""
    state = {}
    cl.record_cell_merge(["C1", "C2"], _merge_obj(), timestamp="2026-07-14_15-20-00", state=state)
    cl.record_cell_merge(["C1", "C2", "C3"], _merge_obj(), timestamp="2026-07-14_15-25-00", state=state)
    merges = [e for e in _events(_isolate_state) if e.get("event_type") == "cell_merge"]
    assert len(merges) == 2, "Geaenderte Parent-Konstellation muss ein neues Event ergeben"


def test_signature_is_timestamp_independent():
    """Kernregel: der Timestamp darf die Ereignisidentitaet NICHT beeinflussen."""
    a = cl._event_signature("cell_merge", ["C1", "C2"], ["C1"])
    b = cl._event_signature("cell_merge", ["C2", "C1"], ["C1"])  # Reihenfolge egal
    assert a == b, "Signatur muss reihenfolgeinvariant sein"


def test_state_last_seen_updates_on_repeat(_isolate_state):
    """Der Zustand muss weiterlaufen, auch wenn kein Event mehr geschrieben wird."""
    state = {}
    cl.record_cell_merge(["C1", "C2"], _merge_obj(), timestamp="2026-07-14_15-20-00", state=state)
    cl.record_cell_merge(["C1", "C2"], _merge_obj(), timestamp="2026-07-14_15-25-00", state=state)
    seen = state.get("emitted_event_last_seen") or {}
    assert "2026-07-14_15-25-00" in seen.values(), "last_seen muss auch ohne neues Event fortschreiben"


def test_repeated_split_writes_single_event(_isolate_state):
    state = {}
    children = [
        {"cell_id": "C10", "id": "T10", "parents": ["T1"], "core_ratio": 0.6, "area": 200.0},
        {"cell_id": "C11", "id": "T11", "parents": ["T1"], "core_ratio": 0.3, "area": 100.0},
    ]
    for _ in range(5):
        cl.record_cell_split("C1", [dict(c) for c in children], timestamp="2026-07-14_15-30-00", state=state)
    splits = [e for e in _events(_isolate_state) if e.get("event_type") == "cell_split"]
    assert len(splits) == 1, f"Erwartet 1 Split-Event, geschrieben: {len(splits)}"


def test_signature_memory_is_bounded(_isolate_state):
    """Das Dedup-Gedaechtnis darf nicht unbegrenzt wachsen (Pi-Diskschutz)."""
    state = {}
    for i in range(50):
        cl._mark_event_emitted(state, f"sig{i}", "2026-07-14_15-00-00")
    assert len(state["emitted_event_signatures"]) <= 2000
    assert len(state["emitted_event_signatures"]) == 50
