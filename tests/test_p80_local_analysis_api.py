"""P80: API fuer Betriebsart und lokale Analyse."""
import ast
import importlib.util
import sys
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
TOOL = ROOT / "tools/run_local_analysis.py"
def _src(): return APP.read_text(encoding="utf-8")
def _body(name): return _src().split(f"def {name}", 1)[1].split("@app.route", 1)[0]
@pytest.fixture
def runner(monkeypatch):
    spec=importlib.util.spec_from_file_location("run_local_analysis_p80", TOOL)
    module=importlib.util.module_from_spec(spec); monkeypatch.setitem(sys.modules,spec.name,module)
    spec.loader.exec_module(module); return module

def test_mode_routes_exist():
    s=_src(); assert '@app.route("/api/analysis_mode")' in s; assert '@app.route("/api/analysis_mode", methods=["POST"])' in s
def test_only_two_modes_are_accepted():
    b=_body("api_analysis_mode_save"); assert '_ANALYSIS_MODES = ("repo", "local")' in _src(); assert "_ANALYSIS_MODES" in b and "400" in b
def test_mode_and_change_date_are_written_in_one_patch(): assert 'runtime_config.patch({"ANALYSIS_MODE": mode, "ANALYSIS_MODE_CHANGED": today})' in _body("api_analysis_mode_save")
def test_switching_to_the_same_mode_does_not_reset_the_date(): assert "if mode == current:" in _body("api_analysis_mode_save")
def test_mode_uses_vienna_time_for_the_change_date(): assert "Europe/Vienna" in _body("api_analysis_mode_save")
def test_local_analysis_routes_exist():
    s=_src(); assert '@app.route("/api/local_analysis/config")' in s; assert '@app.route("/api/local_analysis/config", methods=["POST"])' in s; assert '@app.route("/api/local_analysis/status")' in s
def test_route_handlers_are_defined():
    names={n.name for n in ast.walk(ast.parse(_src())) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
    assert {"api_analysis_mode_get","api_analysis_mode_save","api_local_analysis_config_get","api_local_analysis_config_save","api_local_analysis_status","_local_analysis_module","_analysis_mode_effective"} <= names
def test_routes_require_login():
    b=_src().split("_SENSITIVE_READ_PREFIXES = (",1)[1].split(")",1)[0]; assert '"/api/local_analysis"' in b and '"/api/analysis_mode"' in b
def test_save_rejects_a_second_switch(): assert 'data.pop("enabled", None)' in _body("api_local_analysis_config_save")
def test_save_validates_numeric_ranges():
    b=_body("api_local_analysis_config_save"); assert all(k in b for k in ("cron_hour","cron_minute","max_turns","timeout_s")); assert "0, 23" in b and "0, 59" in b
def test_save_reuses_the_runner_guard_instead_of_copying_it(): assert "_local_analysis_module().validate_allowed_tools" in _body("api_local_analysis_config_save") and "FORBIDDEN_TOOL_TOKENS" not in _src()
def test_guard_rejects_writing_allowlist(runner):
    with pytest.raises(runner.PreconditionError): runner.validate_allowed_tools("Read,Write,Bash(git push *)")
def test_guard_accepts_the_shipped_default(runner):
    import config
    runner.validate_allowed_tools(config.LOCAL_ANALYSIS_CONFIG["allowed_tools"])
def test_manual_run_is_registered_in_the_existing_job_map(): assert '"local_analysis": ("Lokale Analyse jetzt ausführen", _local_analysis)' in _src() and '@app.route("/api/local_analysis/run"' not in _src()
def test_manual_run_uses_force_and_has_a_timeout():
    b=_src().split("def _local_analysis():",1)[1].split("return {",1)[0]; assert '"--force"' in b and "timeout=" in b and "--dangerously-skip-permissions" not in b
def test_manual_run_reports_failure_as_exception(): assert "raise RuntimeError" in _src().split("def _local_analysis():",1)[1].split("return {",1)[0]
def test_status_reports_mode_cli_and_age(): assert all(k in _body("api_local_analysis_status") for k in ('"mode"','"mode_changed"','"cli_available"','"claude_cli"','"result_age_h"','"status"'))
def test_status_survives_a_missing_status_file():
    b=_body("api_local_analysis_status"); assert "except Exception" in b and "status = {}" in b
