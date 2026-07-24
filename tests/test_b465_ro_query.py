"""B465: Tests fuer das streng lesende Abfragewerkzeug."""
from __future__ import annotations
import ast
import importlib.util
import sqlite3
import sys
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "ro_query.py"

@pytest.fixture
def rq(monkeypatch):
    spec = importlib.util.spec_from_file_location("ro_query_b465", TOOL)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module

@pytest.fixture
def probe_db(rq):
    target = REPO / "train_data" / "b465_probe.db"
    target.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(target)
    con.execute("CREATE TABLE t (a INTEGER, b TEXT)")
    con.execute("INSERT INTO t VALUES (1, 'x')")
    con.commit(); con.close()
    yield "train_data/b465_probe.db"
    target.unlink(missing_ok=True)

def test_tool_exists(rq): assert TOOL.is_file()
def test_prompt_uses_only_this_tool():
    txt = (REPO / "docs" / "LOCAL_ANALYSIS_PROMPT.md").read_text(encoding="utf-8")
    assert "tools/ro_query.py" in txt
    for raw in ("journalctl -u", "sqlite3 -readonly", "`df -h`", "`free -m`"): assert raw not in txt

def test_tool_never_uses_a_shell():
    tree = ast.parse(TOOL.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "shell": assert isinstance(kw.value, ast.Constant) and kw.value.value is False
            name = getattr(node.func, "attr", getattr(node.func, "id", ""))
            assert name not in ("system", "popen", "getoutput", "getstatusoutput")

def test_every_subprocess_call_sets_shell_false(rq):
    tree = ast.parse(TOOL.read_text(encoding="utf-8"))
    runs = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "run"]
    assert runs
    for call in runs: assert any(kw.arg == "shell" for kw in call.keywords)

def test_tool_uses_the_readonly_uri_for_sqlite():
    src = TOOL.read_text(encoding="utf-8"); assert "mode=ro" in src and "uri=True" in src

@pytest.mark.parametrize("unit", ["foo.service", "sshd.service", "wetterprojekt.service; rm -rf /", "../wetterprojekt.service", ""])
def test_unknown_units_are_rejected(rq, unit):
    with pytest.raises(rq.QueryError): rq.check_unit(unit)
def test_project_units_are_accepted(rq): assert rq.check_unit("wetterprojekt-scheduler.service")

@pytest.mark.parametrize("value", [0, -1, 169, 100000, "abc", None])
def test_hours_outside_the_range_are_rejected(rq, value):
    with pytest.raises(rq.QueryError): rq.check_hours(value)
def test_hours_inside_the_range_pass(rq): assert rq.check_hours("24") == 24
@pytest.mark.parametrize("prio", ["", "debug", "--vacuum-size=1M", "err;rm"])
def test_unknown_priorities_are_rejected(rq, prio):
    with pytest.raises(rq.QueryError): rq.check_priority(prio)

@pytest.mark.parametrize("rel", ["/etc/passwd", "../../etc/passwd", "../.env", ".env", ".env.local", "certs/server.pem", "certs/server.key", ""])
def test_paths_outside_or_secret_are_rejected(rq, rel):
    with pytest.raises(rq.QueryError): rq.check_inside_repo(rel)
def test_paths_inside_the_project_are_accepted(rq): assert rq.check_inside_repo("docs/LOCAL_ANALYSIS_PROMPT.md").is_file()

@pytest.mark.parametrize("sql", ["SELECT 1; DROP TABLE t", "DELETE FROM t", "UPDATE t SET a=2", "INSERT INTO t VALUES (2,'y')", "DROP TABLE t", "ATTACH DATABASE '/tmp/x' AS y", "PRAGMA quick_check", "VACUUM", "CREATE TABLE x (a)", ".shell rm -rf /", ".output /tmp/x", ""])
def test_writing_or_dot_commands_are_rejected(rq, sql):
    with pytest.raises(rq.QueryError): rq.check_sql(sql)
@pytest.mark.parametrize("sql", ["SELECT a FROM t", "  select * from t where a > 1", "WITH x AS (SELECT 1) SELECT * FROM x"])
def test_plain_selects_pass(rq, sql): assert rq.check_sql(sql)

def test_sqlite_check_reports_ok(rq, probe_db): assert "ok" in rq.cmd_sqlite_check(type("A", (), {"path": probe_db}))
def test_sqlite_tables_lists_rows(rq, probe_db): assert "t: 1 Zeilen" in rq.cmd_sqlite_tables(type("A", (), {"path": probe_db}))
def test_sqlite_select_returns_data(rq, probe_db): assert "1 | x" in rq.cmd_sqlite_select(type("A", (), {"path": probe_db, "sql": "SELECT a,b FROM t"}))
def test_sqlite_connection_is_readonly(rq, probe_db):
    con = rq._connect_readonly(REPO / probe_db)
    try:
        with pytest.raises(sqlite3.OperationalError): con.execute("INSERT INTO t VALUES (9, 'z')")
    finally: con.close()
def test_files_rejects_traversal(rq):
    with pytest.raises(rq.QueryError): rq.cmd_files(type("A", (), {"pattern": "../../etc/*"}))
def test_files_hides_the_env_file(rq): assert ".env" not in rq.cmd_files(type("A", (), {"pattern": ".env*"}))
def test_disk_memory_uptime_return_text(rq):
    for fn in (rq.cmd_disk, rq.cmd_memory, rq.cmd_uptime): assert isinstance(fn(None), str) and fn(None).strip()
def test_unknown_subcommand_exits_nonzero(rq):
    with pytest.raises(SystemExit): rq.build_parser().parse_args(["gibtsnicht"])
def test_invalid_request_returns_exit_code_one(rq, capsys): assert rq.main(["sqlite-check", "/etc/passwd"]) == 1
def test_all_subcommands_are_wired(rq):
    for name in ("services", "journal", "sqlite-check", "sqlite-tables", "sqlite-select", "files", "disk", "memory", "uptime"): assert name in rq.COMMANDS
