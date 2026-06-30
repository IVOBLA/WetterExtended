"""B266: cleanup_radar_names.sh muss sowohl train_data/radar/ als auch
data/radar/ (Live-Serving-Verzeichnis) bereinigen.

End-to-End-Test: kopiert das echte Skript in ein temporäres Projektverzeichnis,
legt Testdateien in beiden Radar-Ordnern an und prüft Umbenennung,
Duplikat-Bereinigung sowie das Verhalten bei fehlendem Verzeichnis.
"""
import os
import shutil
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "cleanup_radar_names.sh")


def _touch(path):
    with open(path, "a", encoding="utf-8"):
        pass


def _run(script_path):
    return subprocess.run(
        ["bash", script_path],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_script_references_both_directories():
    with open(SCRIPT, encoding="utf-8") as fh:
        src = fh.read()
    assert "train_data/radar" in src
    assert "data/radar" in src
    assert "RADAR_DIRS" in src, "Skript muss über ein Array beider Verzeichnisse iterieren"


def test_renames_and_dedups_in_both_dirs(tmp_path):
    script_copy = tmp_path / "cleanup_radar_names.sh"
    shutil.copy(SCRIPT, script_copy)
    os.chmod(script_copy, 0o755)

    train_radar = tmp_path / "train_data" / "radar"
    live_radar = tmp_path / "data" / "radar"
    train_radar.mkdir(parents=True)
    live_radar.mkdir(parents=True)

    # train_data/radar: ein reiner Präfix-Fall + ein Duplikat-Fall
    _touch(train_radar / "radar_2026-06-29_07-00-00.png")
    _touch(train_radar / "radar_2026-06-29_08-00-00.png")
    _touch(train_radar / "2026-06-29_08-00-00.png")

    # data/radar: zwei reine Präfix-Fälle (typisches Live-Bild ohne Duplikate)
    _touch(live_radar / "radar_2026-06-29_07-05-00.png")
    _touch(live_radar / "radar_2026-06-29_07-10-00.png")

    result = _run(str(script_copy))
    assert result.returncode == 0, result.stderr

    train_files = sorted(p.name for p in train_radar.iterdir())
    assert train_files == [
        "2026-06-29_07-00-00.png",
        "2026-06-29_08-00-00.png",
    ], "train_data/radar: Umbenennung/Dedup fehlerhaft"

    live_files = sorted(p.name for p in live_radar.iterdir())
    assert live_files == [
        "2026-06-29_07-05-00.png",
        "2026-06-29_07-10-00.png",
    ], "data/radar: Umbenennung fehlerhaft"

    # Keine radar_*-Reste mehr in beiden Verzeichnissen
    assert not list(train_radar.glob("radar_*.png"))
    assert not list(live_radar.glob("radar_*.png"))


def test_missing_directory_does_not_crash(tmp_path):
    script_copy = tmp_path / "cleanup_radar_names.sh"
    shutil.copy(SCRIPT, script_copy)
    os.chmod(script_copy, 0o755)

    train_radar = tmp_path / "train_data" / "radar"
    train_radar.mkdir(parents=True)
    _touch(train_radar / "radar_2026-06-29_09-00-00.png")
    # data/radar bewusst NICHT angelegt

    result = _run(str(script_copy))
    assert result.returncode == 0, result.stderr
    assert "Verzeichnis nicht vorhanden" in result.stdout

    assert (train_radar / "2026-06-29_09-00-00.png").exists()


def test_idempotent_second_run(tmp_path):
    script_copy = tmp_path / "cleanup_radar_names.sh"
    shutil.copy(SCRIPT, script_copy)
    os.chmod(script_copy, 0o755)

    live_radar = tmp_path / "data" / "radar"
    live_radar.mkdir(parents=True)
    _touch(live_radar / "radar_2026-06-29_07-05-00.png")

    first = _run(str(script_copy))
    assert first.returncode == 0

    second = _run(str(script_copy))
    assert second.returncode == 0
    assert "Umbenannt: 0" in second.stdout or "Gesamt — Umbenannt: 0" in second.stdout

    files = sorted(p.name for p in live_radar.iterdir())
    assert files == ["2026-06-29_07-05-00.png"]
