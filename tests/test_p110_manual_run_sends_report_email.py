import json

import pytest

import importlib
import sys
import types


def _load_app(monkeypatch):
    flask = types.ModuleType("flask")

    class _FakeFlask:
        def __init__(self, *args, **kwargs):
            self.config = {}
        def register_blueprint(self, *args, **kwargs):
            return None
        def route(self, *args, **kwargs):
            return lambda fn: fn
        def before_request(self, fn):
            return fn
        def after_request(self, fn):
            return fn
        def errorhandler(self, *args, **kwargs):
            return lambda fn: fn

    flask.Flask = _FakeFlask
    flask.jsonify = lambda *args, **kwargs: {"args": args, "kwargs": kwargs}
    flask.request = types.SimpleNamespace()
    flask.send_from_directory = lambda *args, **kwargs: None
    flask.send_file = lambda *args, **kwargs: None
    werkzeug = types.ModuleType("werkzeug")
    werkzeug_wsgi = types.ModuleType("werkzeug.wsgi")
    werkzeug_wsgi.ClosingIterator = object
    auth = types.ModuleType("auth")
    auth.auth_bp = object()
    auth.init_db = lambda: None
    auth.get_current_user = lambda: None
    auth.ROLE_LEVEL = {}
    auth.require_role = lambda *args, **kwargs: (lambda fn: fn)
    accuracy_tracker = types.ModuleType("accuracy_tracker")
    accuracy_tracker.evaluate_all = lambda *args, **kwargs: None
    accuracy_tracker.load_history = lambda *args, **kwargs: []
    debug_export = types.ModuleType("debug_export")

    for name, module in {
        "flask": flask,
        "werkzeug": werkzeug,
        "werkzeug.wsgi": werkzeug_wsgi,
        "auth": auth,
        "accuracy_tracker": accuracy_tracker,
        "debug_export": debug_export,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    sys.modules.pop("app", None)
    return importlib.import_module("app")


def _patch_configs(monkeypatch, tmp_path, *, enabled=True, report_email="ops@test.local", result_exists=True):
    app = _load_app(monkeypatch)
    import config

    result_path = tmp_path / "analysis_result.json"
    result = {"summary": "OK", "errors": [], "prompts": ["next"]}
    if result_exists:
        result_path.write_text(json.dumps(result), encoding="utf-8")

    monkeypatch.setattr(
        config,
        "CLAUDE_CODE_REPORT_CONFIG",
        {"enabled": enabled, "report_email": report_email},
    )
    monkeypatch.setattr(
        config,
        "LOCAL_ANALYSIS_CONFIG",
        {"result_path": str(result_path)},
    )
    monkeypatch.setattr(app.runtime_config, "get", lambda _key, default=None: default)
    return app, result


def test_manual_local_analysis_report_email_is_sent(monkeypatch, tmp_path):
    app, result = _patch_configs(monkeypatch, tmp_path)
    import email_notifier

    calls = []
    monkeypatch.setattr(
        email_notifier,
        "send_claude_code_report_email",
        lambda payload, recipient: calls.append((payload, recipient)) or True,
    )

    app._p47_send_local_analysis_report_email()

    assert calls == [(result, "ops@test.local")]


@pytest.mark.parametrize(
    "enabled, report_email, result_exists",
    [
        (False, "ops@test.local", True),
        (True, "", True),
        (True, "ops@test.local", False),
    ],
)
def test_manual_local_analysis_report_email_is_skipped(
    monkeypatch, tmp_path, enabled, report_email, result_exists
):
    app, _result = _patch_configs(
        monkeypatch,
        tmp_path,
        enabled=enabled,
        report_email=report_email,
        result_exists=result_exists,
    )
    import email_notifier

    calls = []
    monkeypatch.setattr(
        email_notifier,
        "send_claude_code_report_email",
        lambda payload, recipient: calls.append((payload, recipient)) or True,
    )

    app._p47_send_local_analysis_report_email()

    assert calls == []


def test_p47_run_sends_manual_local_analysis_email_only_after_success(monkeypatch):
    app = _load_app(monkeypatch)

    calls = []
    monkeypatch.setattr(app, "_p47_send_local_analysis_report_email", lambda: calls.append("sent"))

    app._p47_run("local_analysis", "Lokale Analyse jetzt ausführen", lambda: "OK")
    assert calls == ["sent"]

    calls.clear()

    def _boom():
        raise RuntimeError("kaputt")

    app._p47_run("local_analysis", "Lokale Analyse jetzt ausführen", _boom)
    assert calls == []
