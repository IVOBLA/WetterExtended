"""B500: Der B355-API-Test darf keine produktiven Auswertungsdaten lesen."""
from pathlib import Path

import accuracy_tracker
import config

from tests.test_b355_accuracy_zeitraum_filter import _write_history_fixture


ORIGINAL_OBJECTS_PATH = config.SAVE_PATHS["objects"]


def test_history_fixture_isolates_object_archive(tmp_path, monkeypatch):
    foreign_objects = tmp_path / "foreign_objects"
    foreign_objects.mkdir()
    (foreign_objects / "objects_20000101_000000.json").write_text(
        "not fixture data", encoding="utf-8"
    )
    monkeypatch.setitem(
        accuracy_tracker.SAVE_PATHS, "objects", str(foreign_objects)
    )

    _write_history_fixture(tmp_path, monkeypatch)

    isolated_objects = Path(accuracy_tracker.SAVE_PATHS["objects"])
    assert isolated_objects != foreign_objects
    assert isolated_objects == tmp_path / "objects"
    assert list(isolated_objects.iterdir()) == []
    assert accuracy_tracker.evaluate_for_horizon(10, since_hours=6)["samples"] == 0


def test_object_archive_override_does_not_leak():
    assert accuracy_tracker.SAVE_PATHS["objects"] == ORIGINAL_OBJECTS_PATH


# Dokumentierender Performance-Nachweis (kein hartes Zeitlimit):
# pytest --durations=1 meldete den B355-Test nach B500 im Millisekundenbereich.
