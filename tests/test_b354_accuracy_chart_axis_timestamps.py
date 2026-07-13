"""B354: Reine JS-Formatier-/Lookup-Logik fuer die Zeit-Achsen-Beschriftung der
Accuracy-Charts (MAE/Hit-Rate/ML-Lernfortschritt). Die node:test-Suite wird als
Subprozess ausgefuehrt, damit sie ueber install.sh/pytest erfasst wird — analog
zum bestehenden Muster in frontend/src/utils/hydro.test.js."""
import shutil
import subprocess

import pytest

NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node nicht im PATH gefunden")
def test_chart_time_js_unit_tests_pass():
    result = subprocess.run(
        [NODE, "--test", "chartTime.test.js"],
        cwd="frontend/src/utils",
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        "node --test chartTime.test.js fehlgeschlagen:\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
