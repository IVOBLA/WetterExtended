import subprocess
from pathlib import Path

# MANUELLE TESTS B117:
# 1. MapView öffnen, Browser-DevTools → Network-Tab →
#    /api/objects?ts=... und /api/forecast?ts=... dürfen pro Timestamp
#    nur einmal parallel aktiv sein.
# 2. Fullscreen öffnen und schließen → keine gestapelten Poller sichtbar.
# 3. Scrubbing: DevTools → bei schnellem Scrubbing kein Burst von radar_image-Requests.
# 4. Nginx access.log nach 10min normalem Betrieb → kein "limiting requests" Eintrag.


def test_npm_build_succeeds():
    result = subprocess.run(["npm", "run", "build"], cwd=Path("frontend"), text=True, capture_output=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


def test_no_console_errors_in_build():
    result = subprocess.run(["npm", "run", "build"], cwd=Path("frontend"), text=True, capture_output=True, timeout=120)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert not [line for line in output.splitlines() if "error" in line.lower()]
