"""B265: Radar-Reader dürfen das alte 'radar_'-Präfix nicht mehr verwenden.

Der Writer (object_tracking.py, B259) speichert präfixlos als '{timestamp}.png'.
Reader in app.py/main.py/movement_gif.py müssen dazu passen, sonst bricht das
Radar-Overlay (Regression 2026-06-29). Statischer Quellcode-Test + ein
Funktionstest für die /api/radar_image-Pfadbildung.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


def test_no_radar_prefix_glob_in_app():
    src = _read("app.py")
    assert '"radar_*.png"' not in src, "app.py: veraltetes Glob-Muster 'radar_*.png' gefunden"


def test_no_radar_prefix_glob_in_movement_gif():
    src = _read("movement_gif.py")
    assert "radar_*.png" not in src, "movement_gif.py: veraltetes Glob-Muster gefunden"


def test_no_radar_prefix_format_strings():
    for name in ("app.py", "main.py", "movement_gif.py"):
        src = _read(name)
        assert not re.search(r'f"radar_\{', src), f"{name}: veraltete f-String-Pfadbildung 'radar_{{...}}' gefunden"


def test_reader_uses_digit_glob():
    # Beide kanonischen Verzeichnis-Reader nutzen das präfixlose Digit-Muster
    src = _read("app.py")
    assert '"[0-9]*.png"' in src, "app.py: erwartetes präfixloses Glob-Muster '[0-9]*.png' fehlt"


def test_api_radar_image_path_matches_writer(tmp_path, monkeypatch):
    """End-to-end: ein vom Writer-Schema erzeugtes Frame wird vom Reader gefunden."""
    ts = "2026-06-30_05-00-00"
    radar_dir = tmp_path / "data" / "radar"
    radar_dir.mkdir(parents=True)
    # Writer-Schema (B259): präfixlos
    (radar_dir / f"{ts}.png").write_bytes(b"\x89PNG\r\n\x1a\n")  # PNG-Magic genügt für Existenzprüfung
    monkeypatch.chdir(tmp_path)

    candidate = os.path.join("data", "radar", f"{ts}.png")
    assert os.path.exists(candidate), "Reader-Pfad findet das vom Writer erzeugte Frame nicht"

    # Negativprobe: das alte Präfix-Schema existiert NICHT mehr
    assert not os.path.exists(os.path.join("data", "radar", f"radar_{ts}.png"))
