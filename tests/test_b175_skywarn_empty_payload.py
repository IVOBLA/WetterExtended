"""B175: build_success_snapshot degradiert sauber bei None/Nicht-Dict-Payload."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

skywarn = pytest.importorskip("skywarn_export_snapshot")


def test_none_payload_returns_clean_error():
    snap = skywarn.build_success_snapshot(None)
    assert snap["status"] == "error"
    assert snap["error"]["type"] == "empty_payload"
    assert snap["valid_from"] is None
    assert snap["valid_to"] is None
    assert snap["features_inside_kaernten_bbox"]["features"] == []


def test_non_dict_payload_returns_clean_error():
    snap = skywarn.build_success_snapshot([])
    assert snap["status"] == "error"
    assert snap["error"]["type"] == "empty_payload"
    assert snap["valid_to"] is None
