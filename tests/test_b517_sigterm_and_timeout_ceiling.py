"""B517 — timeout_s-Obergrenze synchron mit systemd TimeoutStartSec anheben
(NICHT auf den alten Default zurueckkappen), SIGTERM-Handler als zweite
Verteidigungslinie, plus Kapazitaets-Diagnose mit konkreten AC-Zahlen.

Vorfall 2026-08-06/07: LOCAL_ANALYSIS_CONFIG.timeout_s war per Admin-Panel auf
3000 gesetzt (API erlaubte bis 3600). wetterprojekt-local-analysis.service hatte
aber TimeoutStartSec=1800 fest in der Unit-Datei -- systemd killte den Prozess
also immer nach 1800s per SIGTERM, lange bevor Pythons eigener
subprocess.run(timeout=3000)-Handler je greifen konnte. Ohne Signal-Handler
blieb local_analysis_status.json auf state=running eingefroren, bis der
naechste geplante Lauf (bis zu 24h spaeter) die Stale-Erkennung ausloeste --
keine Report-Mail in der Zwischenzeit.

B471s detect_incomplete() empfiehlt bei zu knappem Budget explizit
"max_turns/timeout_s erhoehen" -- vermutlich der Grund, warum timeout_s
ueberhaupt auf 3000 gesetzt wurde. Deshalb hier NICHT auf 1700 zurueckgekappt,
sondern TimeoutStartSec auf 3600 angehoben und die Validierungsobergrenze
entsprechend auf 3300 (300s Marge).
"""
import importlib.util
import json
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "run_local_analysis.py"
APP = REPO / "app.py"


@pytest.fixture
def runner(monkeypatch):
    spec = importlib.util.spec_from_file_location("run_local_analysis_b517", TOOL)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_app_py_validation_ceiling_is_at_most_3300():
    text = APP.read_text(encoding="utf-8")
    assert '"timeout_s", 60, 3300' in text
    assert '"timeout_s", 60, 3600' not in text


def test_systemd_unit_timeout_start_sec_is_3600_not_1800():
    unit = (REPO / "wetterprojekt-local-analysis.service").read_text(encoding="utf-8")
    active_lines = [line for line in unit.splitlines() if line.strip().startswith("TimeoutStartSec=")]
    assert len(active_lines) == 1
    assert active_lines[0].strip() == "TimeoutStartSec=3600"


def test_validation_ceiling_has_real_margin_under_systemd_timeout():
    import re
    app_text = APP.read_text(encoding="utf-8")
    unit_text = (REPO / "wetterprojekt-local-analysis.service").read_text(encoding="utf-8")
    ceiling = int(re.search(r'"timeout_s",\s*60,\s*(\d+)', app_text).group(1))
    active_line = next(line for line in unit_text.splitlines() if line.strip().startswith("TimeoutStartSec="))
    timeout_start_sec = int(active_line.strip().split("=", 1)[1])
    assert timeout_start_sec - ceiling >= 200, f"Marge nur {timeout_start_sec - ceiling}s"


def test_config_default_stays_under_ceiling():
    import config
    import re
    app_text = APP.read_text(encoding="utf-8")
    ceiling = int(re.search(r'"timeout_s",\s*60,\s*(\d+)', app_text).group(1))
    assert config.LOCAL_ANALYSIS_CONFIG["timeout_s"] <= ceiling


def _git_init(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.email=test@example.invalid", "-c", "user.name=Test",
                    "commit", "--allow-empty", "-q", "-m", "init"], cwd=tmp_path, check=True)


def test_sigterm_writes_failed_status_instead_of_freezing(tmp_path):
    _git_init(tmp_path)
    binary = tmp_path / "claude"
    binary.write_text('#!/bin/sh\n[ "$1" = "--version" ] && { echo "2.1.206"; exit 0; }\nsleep 300\n', encoding="utf-8")
    binary.chmod(0o755)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "p.md").write_text("Auftrag", encoding="utf-8")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "s.json").write_text(json.dumps({"permissions": {"deny": ["Read(**/.env*)"]}}), encoding="utf-8")
    invoke = tmp_path / "invoke.py"
    invoke.write_text(
        "import sys, importlib.util\n"
        f"spec = importlib.util.spec_from_file_location('rla_b517', {str(TOOL)!r})\n"
        "m = importlib.util.module_from_spec(spec)\nsys.modules[spec.name] = m\nspec.loader.exec_module(m)\n"
        "m.load_mode = lambda repo_dir: ('local', '')\n"
        "m.load_config = lambda repo_dir: {\n'cron_hour': 0, 'cron_minute': 0, 'timeout_s': 60, 'max_turns': 5,\n"
        f"'claude_bin': {str(binary)!r},\n"
        "'allowed_tools': 'Read,Grep,Glob,Bash(python3 tools/ro_query.py *)',\n'prompt_path': 'docs/p.md', 'settings_path': 'tools/s.json',\n'status_path': 'status.json', 'result_path': 'result.json', 'log_path': 'run.log',\n}\n"
        f"raise SystemExit(m.main(['--repo-dir', {str(tmp_path)!r}, '--force']))\n", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, str(invoke)], cwd=str(tmp_path), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    status_path = tmp_path / "status.json"
    running_seen = False
    for _ in range(100):
        if status_path.is_file():
            try:
                if json.loads(status_path.read_text(encoding="utf-8")).get("state") == "running":
                    running_seen = True
                    break
            except Exception:
                pass
        time.sleep(0.1)
    assert running_seen, "Prozess hat nie state=running geschrieben — Testaufbau fehlerhaft"
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        pytest.fail("Prozess hat nicht auf SIGTERM reagiert (Handler nicht registriert?)")
    assert proc.returncode == 143
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["state"] == "failed"
    assert "SIGTERM" in status["error"]
    assert status["rc"] is None
    assert status["duration_s"] is not None


def test_detect_incomplete_without_summary_still_works(runner):
    stdout = json.dumps({"terminal_reason": "max_turns", "errors": []})
    msg = runner.detect_incomplete(stdout)
    assert msg is not None
    assert "Schritt-Limit" in msg


def test_detect_incomplete_includes_open_ac_count_when_available(runner):
    stdout = json.dumps({"terminal_reason": "max_turns", "errors": []})
    msg = runner.detect_incomplete(stdout, {"not_implemented": 35, "implemented": 21})
    assert "35" in msg


def test_detect_incomplete_returns_none_for_normal_completion(runner):
    assert runner.detect_incomplete('{"result": "ok"}', {"not_implemented": 35}) is None


def test_signal_handler_is_a_noop_before_context_is_populated(runner):
    runner._SIGTERM_CONTEXT.clear()
    with pytest.raises(SystemExit) as exc_info:
        runner._handle_sigterm(signal.SIGTERM, None)
    assert exc_info.value.code == 143
