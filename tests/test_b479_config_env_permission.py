"""B479: config.py-Import darf nicht an einer unlesbaren .env abbrechen.

Hintergrund: Der Dienst wetterprojekt-local-analysis.service macht .env per
systemd InaccessiblePaths gezielt unlesbar. python-dotenv wirft dann beim Laden
einen PermissionError (Subklasse von OSError) — NICHT ImportError. Der fruehere
try/except ImportError liess diesen Fehler durch, wodurch der komplette Import
von config.py (und damit der Analyselauf) mit Exit-Code 1 abbrach.

Getestet wird das reale Import-Verhalten von config.py in einem frischen
Subprozess (kein sys.modules-Zustand des Test-Prozesses, kein B96/B160-Risiko):
Eine gefaelschte 'dotenv'-Modulversion wird VOR dem config-Import in sys.modules
gelegt; deren load_dotenv wirft PermissionError bzw. arbeitet normal.
"""
import os
import subprocess
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_import_with_fake_dotenv(raise_permission_error: bool):
    """Importiert config.py im Subprozess mit gefaelschtem python-dotenv.

    raise_permission_error=True  -> load_dotenv wirft PermissionError (Regression)
    raise_permission_error=False -> load_dotenv ist wirkungslos (Positivfall)
    """
    behaviour = (
        "    raise PermissionError(13, 'Permission denied')\n"
        if raise_permission_error
        else "    return False\n"
    )
    code = (
        "import sys, types\n"
        "fake = types.ModuleType('dotenv')\n"
        "def load_dotenv(*a, **k):\n"
        + behaviour
        + "fake.load_dotenv = load_dotenv\n"
        "sys.modules['dotenv'] = fake\n"
        "import config\n"
        "print('CONFIG_IMPORT_OK')\n"
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_config_import_survives_unreadable_env():
    """Regression: PermissionError beim .env-Laden darf den Import NICHT killen."""
    res = _run_import_with_fake_dotenv(raise_permission_error=True)
    assert res.returncode == 0, (
        "config.py-Import brach an PermissionError ab (B479-Regression). "
        f"stderr:\n{res.stderr}"
    )
    assert "CONFIG_IMPORT_OK" in res.stdout
    assert "PermissionError" not in res.stderr


def test_config_import_ok_with_working_dotenv():
    """Positivfall: bei funktionierendem python-dotenv importiert config normal."""
    res = _run_import_with_fake_dotenv(raise_permission_error=False)
    assert res.returncode == 0, res.stderr
    assert "CONFIG_IMPORT_OK" in res.stdout
