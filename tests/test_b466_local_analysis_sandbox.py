"""B466: Der Analyse-Dienst darf nur das Ergebnisverzeichnis beschreiben.

Kernel-erzwungene Grenze zusaetzlich zur Werkzeug-Positivliste aus B465. Selbst
wenn ein Kommando an der Allowlist vorbeikaeme, sind Quellcode, Modelle und
Rohdaten schreibgeschuetzt.
"""
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1] / "wetterprojekt-local-analysis.service"


def _lines(prefix):
    return [l for l in SERVICE.read_text(encoding="utf-8").splitlines()
            if l.startswith(prefix)]


def test_protect_system_is_strict():
    assert _lines("ProtectSystem=") == ["ProtectSystem=strict"]


def test_result_directory_is_writable():
    rw = [l.split("=", 1)[1].lstrip("-") for l in _lines("ReadWritePaths=")]
    assert any(p.endswith("train_data/evaluation") for p in rw)


def test_project_root_is_not_writable():
    rw = [l.split("=", 1)[1].lstrip("-").rstrip("/") for l in _lines("ReadWritePaths=")]
    for p in rw:
        assert not p.endswith("wetterprojekt"), f"Projektwurzel beschreibbar: {p}"
        assert not p.endswith("train_data"), f"Gesamte Rohdaten beschreibbar: {p}"


def test_cli_state_directories_are_writable():
    """Ohne ~/.claude scheitert die Anmeldung; ohne Cache/Config ggf. der Start."""
    rw = " ".join(_lines("ReadWritePaths="))
    for needed in (".claude", ".cache", ".config"):
        assert needed in rw, f"Schreibpfad fehlt: {needed}"


def test_optional_paths_use_the_minus_prefix():
    """Fehlende Heimatverzeichnisse duerfen den Start nicht scheitern lassen."""
    for line in _lines("ReadWritePaths="):
        value = line.split("=", 1)[1]
        if "/.claude" in value or "/.cache" in value or "/.config" in value:
            assert value.startswith("-"), f"Minus-Praefix fehlt: {line}"


def test_env_file_stays_inaccessible():
    line = next(iter(_lines("InaccessiblePaths=")), "")
    assert ".env" in line and line.startswith("InaccessiblePaths=-")
