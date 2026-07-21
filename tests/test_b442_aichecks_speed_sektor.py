"""B442: Speed-/Sektor-Diagnose ist als B407-konforme Arbeitsanweisung hinterlegt."""
from pathlib import Path

AICHECKS = Path("AIChecks.md").read_text(encoding="utf-8")


def test_ac068_existiert_und_ist_imperativ():
    heads = [l for l in AICHECKS.splitlines() if l.startswith("### AC-068")]
    assert heads, "AC-068 fehlt in AIChecks.md"
    title = heads[0].split("—", 1)[1].strip()
    verbs = ("Prüfe", "Kalibriere", "Messe", "Suche", "Nimm", "Zähle", "Werte",
             "Führe", "Setze", "Vergleiche", "Bilde", "Sammle")
    assert title.startswith(verbs), f"AC-068-Titel nicht imperativ: {title}"


def test_ac068_steht_im_offen_bereich():
    offen = AICHECKS.split("## Offen", 1)[1].split("## Erledigt", 1)[0]
    assert "### AC-068" in offen, "AC-068 muss im Offen-Bereich stehen"


def test_ac068_nennt_datenquellen():
    block = AICHECKS.split("### AC-068", 1)[1].split("## Erledigt", 1)[0]
    assert "latest_objects.json" in block
    assert "train_data/objects" in block


def test_ac068_dokumentiert_keine_messwerte():
    """B407: AIChecks weist an, dokumentiert keine Befunde/Messwerte."""
    block = AICHECKS.split("### AC-068", 1)[1].split("## Erledigt", 1)[0]
    assert "**Befund:**" not in block
    assert "| Lage |" not in block
    # Keine konkreten gemessenen km/h-Werte als Feststellung (Schwellen wie 60/45 sind
    # Prüfmaßstäbe, keine Messungen — die sind erlaubt).


def test_b407_regeln_fuer_ac068_erfuellt():
    """B449: früher wurde pytest als Subprozess gestartet — das scheitert in der
    install.sh-Umgebung, wo pytest im System-python3 fehlt (No module named pytest).
    Stattdessen die für AC-068 relevanten B407-Regeln direkt prüfen."""
    from pathlib import Path
    ac = Path("AIChecks.md").read_text(encoding="utf-8")
    block = ac.split("### AC-068", 1)
    assert len(block) == 2, "AC-068 fehlt"
    body = "### AC-068" + block[1].split("### AC-", 1)[0]
    # Imperativ-Titel
    title = body.splitlines()[0].split("—", 1)[1].strip()
    verbs = ("Prüfe", "Kalibriere", "Messe", "Suche", "Nimm", "Zähle", "Werte",
             "Führe", "Setze", "Vergleiche", "Bilde", "Sammle")
    assert title.startswith(verbs), f"AC-068-Titel nicht imperativ: {title}"
    # Datenquelle benannt
    assert any(s in body for s in (".json", ".jsonl", "grep", "Log", "log", "Export")), \
        "AC-068 nennt keine Datenquelle"
    # keine Messwerte/Befunde im Anweisungstext
    assert "**Befund:**" not in body
