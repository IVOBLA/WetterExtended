"""B457: Quarantaene laeuft unter dem State-Lock und prueft die Datei erneut."""
import json
from types import SimpleNamespace

import cell_lineage as cl


def _patch_state(monkeypatch, tmp_path):
    state_file = tmp_path / "cell_lineage_state.json"
    monkeypatch.setattr(cl, "_state_path", lambda: state_file)
    return state_file


def _patch_flock_hook(monkeypatch, hook):
    """Ersetzt cl.fcntl durch einen Wrapper, der beim ersten LOCK_EX `hook`
    ausfuehrt -- simuliert einen anderen Prozess, der VOR dem Lock-Erwerb
    dieses Prozesses die Datei veraendert (das Codex-P1-Race)."""
    import fcntl as real_fcntl
    fired = {"done": False}

    def _flock(fd, op):
        if op == real_fcntl.LOCK_EX and not fired["done"]:
            fired["done"] = True
            hook()
        return real_fcntl.flock(fd, op)

    monkeypatch.setattr(cl, "fcntl", SimpleNamespace(
        flock=_flock, LOCK_EX=real_fcntl.LOCK_EX, LOCK_UN=real_fcntl.LOCK_UN))


def test_no_quarantine_when_other_process_repaired(monkeypatch, tmp_path):
    state_file = _patch_state(monkeypatch, tmp_path)
    state_file.write_text('{"cells": {}}\n{"cells": {}}\n', encoding="utf-8")

    def _repair():
        valid = cl._empty_state()
        valid["date_counters"] = {"2026-07-22": 7}
        state_file.write_text(json.dumps(valid), encoding="utf-8")

    _patch_flock_hook(monkeypatch, _repair)
    result = cl.load_lineage_state()

    assert result.get("date_counters", {}).get("2026-07-22") == 7, \
        "Der von einem anderen Prozess reparierte State muss zurueckgegeben werden"
    assert state_file.exists(), "Valider State wurde faelschlich quarantaeniert"
    assert [p.name for p in tmp_path.iterdir() if ".corrupt." in p.name] == []


def test_still_corrupt_is_quarantined_under_lock(monkeypatch, tmp_path):
    state_file = _patch_state(monkeypatch, tmp_path)
    state_file.write_text('{"cells": {}}\n{"cells": {}}\n', encoding="utf-8")
    _patch_flock_hook(monkeypatch, lambda: None)  # niemand repariert

    result = cl.load_lineage_state()

    assert isinstance(result, dict)
    assert not state_file.exists(), "Weiterhin defekte Datei muss quarantaeniert werden"
    corrupt = [p.name for p in tmp_path.iterdir() if ".corrupt." in p.name]
    assert len(corrupt) == 1, f"Quarantaene-Datei fehlt oder mehrfach: {corrupt}"


def test_file_vanished_between_parse_and_lock(monkeypatch, tmp_path):
    state_file = _patch_state(monkeypatch, tmp_path)
    state_file.write_text('{"cells": {}}\n{"cells": {}}\n', encoding="utf-8")
    _patch_flock_hook(monkeypatch, lambda: state_file.unlink())  # anderer Prozess quarantaeniert zuerst

    result = cl.load_lineage_state()

    assert isinstance(result, dict)
    assert result.get("cells") == {}
    assert not state_file.exists()
    assert [p.name for p in tmp_path.iterdir() if ".corrupt." in p.name] == []
