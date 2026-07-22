"""B453: Lineage-State-Persistenz prozesssicher; defekte States werden quarantaeniert."""
import json
from concurrent.futures import ThreadPoolExecutor

import cell_lineage as cl


def _patch_state(monkeypatch, tmp_path):
    state_file = tmp_path / "cell_lineage_state.json"
    monkeypatch.setattr(cl, "_state_path", lambda: state_file)
    return state_file


def test_concurrent_saves_leave_single_valid_json(monkeypatch, tmp_path):
    state_file = _patch_state(monkeypatch, tmp_path)

    def _save(i):
        st = cl._empty_state()
        st.setdefault("radar_to_cell", {})[f"R{i}"] = f"WX-20260101-{i:04d}"
        cl.save_lineage_state(st)

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(_save, range(24)))

    raw = state_file.read_text(encoding="utf-8")
    parsed = json.loads(raw)  # genau EIN gueltiges JSON-Dokument, kein "Extra data"
    assert isinstance(parsed, dict)
    leftovers = [p.name for p in tmp_path.iterdir() if ".tmp" in p.name]
    assert leftovers == [], f"Temp-Dateien zurueckgeblieben: {leftovers}"


def test_unique_tmp_name_per_call(monkeypatch, tmp_path):
    _patch_state(monkeypatch, tmp_path)
    seen = []
    orig_replace = cl.os.replace

    def _spy(src, dst):
        seen.append(str(src))
        return orig_replace(src, dst)

    monkeypatch.setattr(cl.os, "replace", _spy)
    cl.save_lineage_state(cl._empty_state())
    cl.save_lineage_state(cl._empty_state())
    assert len(seen) == 2 and seen[0] != seen[1], "Temp-Name nicht eindeutig pro Aufruf"
    assert all(".tmp" in s for s in seen)


def test_corrupt_state_is_quarantined_on_load(monkeypatch, tmp_path):
    state_file = _patch_state(monkeypatch, tmp_path)
    # Signatur des Produktionsfehlers: zwei aneinandergehaengte JSON-Dokumente.
    state_file.write_text('{"cells": {}}\n{"cells": {}}\n', encoding="utf-8")

    result = cl.load_lineage_state()

    assert isinstance(result, dict)
    assert not state_file.exists(), "Defekte Datei wurde nicht entfernt"
    corrupt = [p.name for p in tmp_path.iterdir() if ".corrupt." in p.name]
    assert len(corrupt) == 1, f"Quarantaene-Datei fehlt oder mehrfach: {corrupt}"
    # Folgelauf: sauberer Save + Load funktionieren wieder.
    cl.save_lineage_state(cl._empty_state())
    assert isinstance(cl.load_lineage_state(), dict)
    assert state_file.exists()
