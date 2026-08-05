import importlib.util
from pathlib import Path

import pytest


def _load_p110_test_module():
    module_path = Path(__file__).with_name("test_p110_manual_run_sends_report_email.py")
    spec = importlib.util.spec_from_file_location("test_p110_manual_run_sends_report_email", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_b512_1_load_app_uses_monkeypatch_isolated_app_slot(monkeypatch):
    p110 = _load_p110_test_module()

    loaded_app = p110._load_app(monkeypatch)

    assert not hasattr(loaded_app.app, "test_client")


def test_b512_2_later_import_gets_real_flask_app_after_p110_loader_teardown():
    flask_testing = pytest.importorskip("flask.testing")
    import app as app_module

    assert callable(app_module.app.test_client)
    assert isinstance(app_module.app.test_client(), flask_testing.FlaskClient)
