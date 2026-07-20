"""B440: Es wird über keinen Kanal eine Entwarnung gesendet.

Horst-Entscheidung 2026-07-20. Bisher sendete main.py eine E-Mail-Entwarnung, wenn ein
gewarnter Ort keine Zellen mehr hatte. Der an die Entwarnung gekoppelte Zustands-Reset
(_location_warned / _warned_cells) muss erhalten bleiben, sonst warnt ein Ort nach dem
ersten Alarm nie wieder.
"""
import re
from pathlib import Path

MAIN = Path("main.py").read_text(encoding="utf-8")


def test_kein_send_allclear_email_aufruf_in_main():
    # Import und Aufruf müssen aus main.py verschwunden sein.
    assert "send_allclear_email" not in MAIN, \
        "main.py ruft weiterhin send_allclear_email auf — Entwarnung wird gesendet."


def test_kein_send_allclear_wa_aufruf_in_main():
    assert "send_allclear_wa" not in MAIN


def test_warn_reset_bleibt_erhalten():
    # Der Zustands-Reset muss weiterhin im _cleared-Zweig stehen.
    assert "_location_warned.discard(_loc_name)" in MAIN, \
        "Warn-Sperre wird nicht mehr zurückgenommen — Ort würde nie wieder warnen."
    assert "_warned_cells.pop(_loc_name, None)" in MAIN


def test_reset_haengt_an_cleared_und_location_warned():
    """Der Reset darf nur greifen, wenn der Ort zuvor gewarnt war und jetzt frei ist."""
    block = MAIN[MAIN.find("Entwarnung: KEIN Versand"):MAIN.find("WhatsApp: Entwarnung bewusst NICHT")]
    assert "if _cleared:" in block
    assert "if _loc_name in _location_warned:" in block


def test_kein_allclear_versand_ueber_notifier_module():
    """Gegenprobe: auch kein anderer Modulpfad ruft die Entwarnungsfunktionen auf."""
    import subprocess
    res = subprocess.run(
        ["grep", "-rn", "send_allclear", "--include=*.py", "."],
        capture_output=True, text=True,
    )
    aufrufer = [l for l in res.stdout.splitlines()
                if "def send_allclear" not in l and "/tests/" not in l and not l.startswith("./tests/")]
    assert aufrufer == [], f"Unerwartete Entwarnungs-Aufrufer: {aufrufer}"
