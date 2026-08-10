"""B522: wetterprojekt-nightly-analysis.service muss WorkingDirectory setzen, sonst
loest runtime_config.get("ANALYSIS_MODE", ...) den persistierten Override nie auf,
weil RUNTIME_OVERRIDES_PATH relativ ist und der Dispatcher sonst mit cwd=/ startet."""
import re
from pathlib import Path

import config as _cfg

SERVICE_FILE = Path(__file__).resolve().parent.parent / "wetterprojekt-nightly-analysis.service"


def test_b522_service_file_exists():
    assert SERVICE_FILE.is_file(), f"{SERVICE_FILE} fehlt"


def test_b522_working_directory_present_and_matches_execstart_path():
    text = SERVICE_FILE.read_text(encoding="utf-8")
    m_wd = re.search(r"^WorkingDirectory=(.+)$", text, re.MULTILINE)
    m_exec = re.search(r"^ExecStart=(\S+)\s+(\S+)$", text, re.MULTILINE)
    assert m_wd, "WorkingDirectory=-Zeile fehlt in wetterprojekt-nightly-analysis.service"
    assert m_exec, "ExecStart=-Zeile nicht im erwarteten Format gefunden"
    workdir = m_wd.group(1).strip()
    exec_arg = m_exec.group(2).strip()  # zweites Argument von ExecStart ist der Repo-Pfad
    assert workdir == exec_arg, (
        f"WorkingDirectory ({workdir}) muss mit dem an nightly_analysis_dispatch.sh "
        f"uebergebenen Repo-Pfad ({exec_arg}) uebereinstimmen"
    )


def test_b522_working_directory_line_appears_exactly_once():
    text = SERVICE_FILE.read_text(encoding="utf-8")
    assert text.count("WorkingDirectory=") == 1


def test_b522_runtime_overrides_path_is_relative_confirming_bug_precondition():
    """Dokumentiert die Kernannahme: RUNTIME_OVERRIDES_PATH ist relativ, daher ist
    WorkingDirectory fuer JEDEN Prozess, der runtime_config nutzt, sicherheitskritisch."""
    path = getattr(_cfg, "RUNTIME_OVERRIDES_PATH", "")
    assert path and not path.startswith("/"), (
        "RUNTIME_OVERRIDES_PATH ist nicht mehr relativ — B522-Fix (WorkingDirectory) "
        "waere dann nicht mehr die richtige Absicherung; bitte Auftrag neu bewerten"
    )


def test_b522_install_sh_sed_pattern_would_rewrite_new_line():
    """Stellt sicher, dass das bestehende install.sh-sed-Muster die neue
    WorkingDirectory-Zeile bei Neuinstallation korrekt auf $TARGET umschreibt —
    ohne install.sh selbst aendern zu muessen."""
    text = SERVICE_FILE.read_text(encoding="utf-8")
    m_wd = re.search(r"^WorkingDirectory=(.+)$", text, re.MULTILINE)
    assert m_wd and m_wd.group(1).strip() == "/home/ki-pi/wetterprojekt", (
        "WorkingDirectory muss den literalen Pfad /home/ki-pi/wetterprojekt enthalten, "
        "damit install.sh's 's|/home/ki-pi/wetterprojekt|$TARGET|g' ihn korrekt ersetzt"
    )
