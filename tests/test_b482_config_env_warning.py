"""B482: .env-Unlesbarkeit sauber behandeln — sichtbare Warnung statt stillem pass.

Hintergrund: B479 fing OSError beim .env-Laden mit `except (ImportError, OSError): pass`
ab. Das behob den Sandbox-Crash, verschluckte aber auch einen ECHTEN .env-Rechtefehler
der Produktionsdienste (main/scheduler/admin) still — kein Push, keine Mail, Admin-Auth
defekt, ohne Journal-Signal. B482 trennt die Faelle: fehlendes python-dotenv -> still
(ImportError); unlesbare .env -> weiterlaufen MIT sichtbarer Warnung (OSError), damit ein
echter Rechtefehler diagnostizierbar bleibt. Import ueberlebt weiterhin (B479-Regression).
"""
import os
import subprocess
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(raise_permission_error: bool):
    behaviour = (
        "    raise PermissionError(13, 'Permission denied')\n"
        if raise_permission_error else "    return False\n"
    )
    code = (
        "import sys, types\n"
        "fake = types.ModuleType('dotenv')\n"
        "def load_dotenv(*a, **k):\n" + behaviour +
        "fake.load_dotenv = load_dotenv\n"
        "sys.modules['dotenv'] = fake\n"
        "import config\n"
        "print('CONFIG_IMPORT_OK')\n"
    )
    return subprocess.run([sys.executable, "-c", code], cwd=_REPO_ROOT,
                          capture_output=True, text=True, timeout=120)


def test_unreadable_env_emits_visible_warning():
    res = _run(True)
    assert res.returncode == 0, res.stderr
    assert "CONFIG_IMPORT_OK" in res.stdout
    assert "[CONFIG] .env nicht lesbar" in (res.stdout + res.stderr), (
        "unlesbare .env muss eine sichtbare Warnung erzeugen (kein stilles pass)")


def test_working_dotenv_no_warning():
    res = _run(False)
    assert res.returncode == 0, res.stderr
    assert "CONFIG_IMPORT_OK" in res.stdout
    assert "[CONFIG] .env nicht lesbar" not in (res.stdout + res.stderr)
