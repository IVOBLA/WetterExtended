"""B228 — NN-Akzeptanzschwelle: NN jenseits Schwelle wird verworfen,
ID-/cell_id-Treffer bleiben distanzunabhaengig gueltig."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import accuracy_tracker as at


def test_default_threshold_from_config():
    from config import VERIFICATION_NN_MAX_MATCH_KM
    assert at._nn_max_match_km() == float(VERIFICATION_NN_MAX_MATCH_KM)


def test_runtime_override(monkeypatch):
    class _Stub:
        @staticmethod
        def get(name, default=None):
            return 5.0
    monkeypatch.setattr(at, "_runtime_cfg", _Stub())
    assert at._nn_max_match_km() == 5.0


def test_nn_beyond_threshold_is_rejected():
    obj = {"id": "x"}
    assert at._is_nn_rejected("nn", obj, 12.0, 10.0) is True


def test_nn_within_threshold_is_accepted():
    obj = {"id": "x"}
    assert at._is_nn_rejected("nn", obj, 8.0, 10.0) is False


def test_id_match_never_rejected_regardless_of_distance():
    obj = {"id": "x"}
    assert at._is_nn_rejected("id", obj, 50.0, 10.0) is False


def test_cell_id_match_never_rejected_regardless_of_distance():
    obj = {"id": "x"}
    assert at._is_nn_rejected("cell_id", obj, 30.0, 10.0) is False


def test_no_match_is_not_rejected():
    assert at._is_nn_rejected("nn", None, 5.0, 10.0) is False
    assert at._is_nn_rejected("miss", None, math.inf, 10.0) is False
