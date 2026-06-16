"""B168 — Regressionstest: Lernfortschritt-Seite trennt Fehler / Leer / Modus.

Statische Quellpruefung (kein Node noetig), via install.sh/pytest ausfuehrbar.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROGRESS = ROOT / "frontend" / "src" / "pages" / "Progress.jsx"


def _src():
    assert PROGRESS.exists(), f"{PROGRESS} fehlt"
    return PROGRESS.read_text(encoding="utf-8")


def test_progress_jsx_exists():
    _src()


def test_no_silent_error_swallowing():
    # Der fruehere Fehlerschlucker '.catch(() => { setLoaded(true) })' darf nicht
    # mehr existieren — Fehler muessen ueber loadError sichtbar werden.
    src = _src()
    assert "setLoadError" in src, "loadError-State fehlt — Fehler werden nicht unterschieden"
    assert re.search(
        r"catch\(\s*\(\s*\)\s*=>\s*\{\s*setLoaded\(true\)\s*\}\s*\)", src
    ) is None, "Stiller Fehlerschlucker im /api/progress-Catch noch vorhanden"


def test_active_mode_from_forecast_stats():
    src = _src()
    assert "/api/forecast_stats" in src, "Progress nutzt forecast_stats nicht als Modus-Quelle"
    assert "ml_blocked_reason" in src, "ml_blocked_reason (B116) wird nicht ausgewertet"


def test_no_hardcoded_inactive_claim_in_empty_state():
    # Die statische Falschbehauptung darf nicht mehr im Quelltext stehen.
    src = _src()
    assert "kein trainiertes Modell aktiv" not in src, \
        "Statische Falschbehauptung 'kein trainiertes Modell aktiv' noch vorhanden"


def test_error_card_and_retry_present():
    src = _src()
    assert "loadError" in src and "Erneut versuchen" in src, \
        "Fehler-Karte mit Retry fehlt"


if __name__ == "__main__":
    import sys
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failed += 1
                print(f"FAIL {name}: {exc}")
    sys.exit(1 if failed else 0)
