"""B476 — Ein gemeinsamer 23:59-Ausloeser (Dispatcher) statt zweitem Timer."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DISPATCH = ROOT / "tools/nightly_analysis_dispatch.sh"
DISPATCH_SVC = ROOT / "wetterprojekt-nightly-analysis.service"
EXPORT_TIMER = ROOT / "wetterprojekt-debug-export-branch.timer"
OLD_TIMER = ROOT / "wetterprojekt-local-analysis.timer"
LOCAL_SVC = ROOT / "wetterprojekt-local-analysis.service"
INSTALL = ROOT / "install.sh"
JSX = ROOT / "frontend/src/pages/AiSuggestions.jsx"
HB = ROOT / "docs/WetterExtended_Benutzerhandbuch.md"


def test_dispatch_script_is_valid_sh():
    assert DISPATCH.is_file()
    subprocess.run(["sh", "-n", str(DISPATCH)], check=True)


def test_dispatch_routes_both_modes():
    s = DISPATCH.read_text(encoding="utf-8")
    assert "wetterprojekt-local-analysis.service" in s
    assert "wetterprojekt-debug-export-branch.service" in s
    assert "ANALYSIS_MODE" in s and 'MODE" = "local"' in s.replace("$", "")


def test_dispatcher_service_is_oneshot_and_calls_script():
    s = DISPATCH_SVC.read_text(encoding="utf-8")
    assert "Type=oneshot" in s
    assert "tools/nightly_analysis_dispatch.sh" in s


def test_shared_timer_points_to_dispatcher():
    s = EXPORT_TIMER.read_text(encoding="utf-8")
    assert "Unit=wetterprojekt-nightly-analysis.service" in s
    assert "23:59" in s


def test_old_half_hourly_timer_removed():
    assert not OLD_TIMER.exists(), "wetterprojekt-local-analysis.timer muss entfernt sein"


def test_local_service_still_exists():
    assert LOCAL_SVC.is_file(), "Der gehaertete lokale Analyse-Dienst wird weiter gebraucht"


def test_install_no_longer_enables_half_hourly_timer():
    s = INSTALL.read_text(encoding="utf-8")
    assert 'enable --now "$LOCAL_ANALYSIS_TIMER"' not in s
    assert "wetterprojekt-nightly-analysis.service" in s
    assert 'rm -f "/etc/systemd/system/$LOCAL_ANALYSIS_TIMER"' in s


def test_frontend_drops_schedule_keeps_tuning():
    j = JSX.read_text(encoding="utf-8")
    assert "Faellig ab Stunde" not in j
    assert "Faellig ab Minute" not in j
    assert "Max. Arbeitsschritte" in j
    assert "Zeitlimit in Sekunden" in j


def test_handbook_mentions_shared_trigger():
    assert "23:59" in HB.read_text(encoding="utf-8")
