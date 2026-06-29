"""B259: Radarframes werden ohne radar_-Präfix archiviert."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _object_tracking_source():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(repo_root, "object_tracking.py"), encoding="utf-8") as handle:
        return handle.read()


def test_scaled_path_no_prefix():
    """Der skalierte Radarframe wird ohne radar_-Präfix gespeichert."""
    source = _object_tracking_source()

    assert 'scaled_path = os.path.join("data/radar", f"{timestamp}.png")' in source
    assert 'scaled_path = os.path.join("data/radar", f"radar_{timestamp}.png")' not in source


def test_original_path_no_prefix():
    """SAVE_PATHS['radar']-Archivpfad enthält kein radar_-Präfix."""
    source = _object_tracking_source()

    expected = 'original_path = os.path.join(SAVE_PATHS["radar"].rstrip("/"), f"{timestamp}.png")'
    forbidden = 'original_path = os.path.join(SAVE_PATHS["radar"].rstrip("/"), f"radar_{timestamp}.png")'
    assert expected in source
    assert forbidden not in source


def test_radar_prefix_strip_stays_for_backward_compatibility():
    """Rückwärtskompatibilität: Alte radar_-Dateinamen werden beim Einlesen weiter toleriert."""
    source = _object_tracking_source()

    assert 'filename.replace("radar_", "")' in source


def test_regression_parse_ts_no_prefix():
    """accuracy_tracker._parse_ts() parst präfixfreien Dateinamen korrekt."""
    from accuracy_tracker import _parse_ts
    from datetime import datetime

    result = _parse_ts("train_data/objects/2026-06-28_12-00-00.json")
    assert result == datetime(2026, 6, 28, 12, 0, 0)


def test_regression_parse_ts_with_prefix_still_works():
    """Rückwärtskompatibilität: Präfix-Frames aus früheren Archiven werden toleriert."""
    from accuracy_tracker import _parse_ts

    # _parse_ts erwartet Timestamp ohne Präfix — mit Präfix ergibt sich None (kein Crash)
    result = _parse_ts("train_data/radar/radar_2026-06-28_12-00-00.png")
    assert result is None  # wird still verworfen, kein Absturz
