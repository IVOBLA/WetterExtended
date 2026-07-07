"""
B316: Die Radar-Ingest-Gesundheitsbewertung leitet den erwarteten Takt dynamisch aus
der tatsaechlichen Zellaktivitaet im Bewertungsfenster ab, statt immer den aktiven
Takt (FRAME_INTERVAL_MIN=5) anzunehmen. Ohne Zellen im Fenster wird der Ruhetakt
(LOOP_INTERVAL_NO_CELLS_S/60) erwartet, damit ruhige Wetterlagen nicht faelschlich
als 'critical' eingestuft werden.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _setup(monkeypatch, tmp_path):
    import importlib
    obj_dir = tmp_path / "objects"
    obj_dir.mkdir()
    db = importlib.import_module("dataset_builder")
    importlib.reload(db)
    monkeypatch.setitem(db.SAVE_PATHS, "objects", str(obj_dir))
    return db, obj_dir


def test_expected_interval_is_idle_when_no_cells_present(monkeypatch, tmp_path):
    db, obj_dir = _setup(monkeypatch, tmp_path)
    stamp = __import__("datetime").datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
    (obj_dir / f"{stamp}.json").write_text(json.dumps([]), encoding="utf-8")
    result = db._expected_radar_interval_min(24)
    assert result == db.LOOP_INTERVAL_NO_CELLS_S / 60.0


def test_expected_interval_is_active_when_cells_present(monkeypatch, tmp_path):
    db, obj_dir = _setup(monkeypatch, tmp_path)
    stamp = __import__("datetime").datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
    (obj_dir / f"{stamp}.json").write_text(json.dumps([{"id": "WX-1", "lat": 46.6, "lon": 14.3}]), encoding="utf-8")
    result = db._expected_radar_interval_min(24)
    assert result == float(db.FRAME_INTERVAL_MIN)


def test_expected_interval_defaults_to_idle_when_no_files(monkeypatch, tmp_path):
    db, obj_dir = _setup(monkeypatch, tmp_path)
    result = db._expected_radar_interval_min(24)
    assert result == db.LOOP_INTERVAL_NO_CELLS_S / 60.0


def test_expected_interval_never_raises_on_corrupt_file(monkeypatch, tmp_path):
    db, obj_dir = _setup(monkeypatch, tmp_path)
    stamp = __import__("datetime").datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
    (obj_dir / f"{stamp}.json").write_text("{not valid json", encoding="utf-8")
    result = db._expected_radar_interval_min(24)
    assert result == db.LOOP_INTERVAL_NO_CELLS_S / 60.0
