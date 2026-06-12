"""
tests/test_b129_api_health_isolation.py

B129: log_api_failure() schreibt waehrend Tests NICHT in die Produktions-
api_health.jsonl, sondern in einen pro Test umgelenkten tmp-Pfad.

Ausfuehrbar: python3 -m pytest tests/test_b129_api_health_isolation.py -v
"""
import os
import pytest


def test_api_health_path_is_redirected():
    debug_utils = pytest.importorskip("debug_utils")
    from config import SAVE_PATHS
    prod = os.path.abspath(
        os.path.join(SAVE_PATHS.get("evaluation", "train_data/evaluation").rstrip("/"),
                     "api_health.jsonl")
    )
    cur = os.path.abspath(debug_utils._API_HEALTH_FILE)
    assert cur != prod, "api_health.jsonl muss waehrend Tests umgelenkt sein (B129)"


def test_log_api_failure_writes_only_to_isolated_file():
    debug_utils = pytest.importorskip("debug_utils")
    debug_utils.log_api_failure(
        "Open-Meteo-Outlook", "http://example/forecast",
        "RuntimeError: x", fallback_used=True,
    )
    p = debug_utils._API_HEALTH_FILE
    assert os.path.exists(p), "Eintrag muss in den umgelenkten tmp-Pfad geschrieben werden"
    assert "RuntimeError: x" in open(p, encoding="utf-8").read()
