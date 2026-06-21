"""
B225 — Die Admin-API muss über einen nebenläufigen WSGI-Server (waitress) laufen,
nicht über den single-threaded Flask-Dev-Server. Der Dev-Server blockiert unter
Karten-Bursts den GIL → Watchdog-Heartbeat verhungert → systemd-Kill/Restart-Loop.
"""
import pathlib
import subprocess


def _repo_root() -> pathlib.Path:
    p = pathlib.Path(__file__).resolve()
    for parent in [p, *p.parents]:
        if (parent / "app.py").is_file():
            return parent
    raise AssertionError("Repo-Root (app.py) nicht gefunden")


ROOT = _repo_root()
APP = ROOT / "app.py"
REQ = ROOT / "requirements.txt"


def test_app_py_compiles():
    r = subprocess.run(["python3", "-m", "py_compile", str(APP)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_serves_via_waitress_with_threaded_fallback():
    s = APP.read_text()
    assert "from waitress import serve as _serve" in s, "waitress wird nicht verwendet"
    assert "_serve(app, host=_bind_host, port=_bind_port" in s, "waitress.serve-Aufruf fehlt"
    assert "app.run(host=_bind_host, port=_bind_port, threaded=True)" in s, "threaded-Fallback fehlt"


def test_no_bare_single_threaded_run():
    s = APP.read_text()
    assert 'app.run(host=_bind_host, port=_bind_port, debug=os.getenv("ADMIN_DEBUG") == "1")' not in s, \
        "single-threaded Dev-Server-Aufruf noch vorhanden"


def test_requirements_lists_waitress():
    assert "waitress" in REQ.read_text().lower(), "waitress fehlt in requirements.txt"
