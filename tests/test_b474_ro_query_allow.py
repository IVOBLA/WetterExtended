"""B474 — Die Deny-Regeln duerfen den einzigen erlaubten Shell-Zugang nicht verdecken."""
import importlib.util
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SETTINGS = REPO / "tools" / "local_analysis_settings.json"
RUNNER = REPO / "tools" / "run_local_analysis.py"


def _deny():
    return json.loads(SETTINGS.read_text(encoding="utf-8"))["permissions"]["deny"]


def test_python_deny_removed():
    assert not any(r.startswith("Bash(python") for r in _deny()), \
        "Bash(python*)-Deny wuerde 'python3 tools/ro_query.py' blockieren"


def test_ro_query_not_shadowed():
    deny = _deny()
    for verboten in ("Bash(python *)", "Bash(python3 *)"):
        assert verboten not in deny


def test_load_bearing_rules_survived():
    deny = _deny()
    for needed in ("Bash(rm *)", "Bash(sudo *)", "Bash(git push *)", "Read(**/.env)"):
        assert needed in deny


def test_runner_still_accepts_settings():
    spec = importlib.util.spec_from_file_location("rla_b474", RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.validate_deny_rules(json.loads(SETTINGS.read_text(encoding="utf-8")), SETTINGS)
