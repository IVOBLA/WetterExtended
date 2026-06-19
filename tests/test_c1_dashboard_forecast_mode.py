"""C.1 — Dashboard-Forecast-Modus nutzt aktuellen ML-Blockstatus.

Statische Quellpruefung (kein Node noetig): Das Dashboard muss
ml_blocked_reason als aktuellen Produktivzustand priorisieren, damit es der
Lernfortschritt-Seite nicht widerspricht.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD = ROOT / "frontend" / "src" / "pages" / "Dashboard.jsx"
PROGRESS = ROOT / "frontend" / "src" / "pages" / "Progress.jsx"


def _src(path):
    assert path.exists(), f"{path} fehlt"
    return path.read_text(encoding="utf-8")


def _forecast_mode_block():
    src = _src(DASHBOARD)
    match = re.search(
        r"const runtimeStatus = forecastStats\?\.runtime_status \|\| \{}(?P<block>.*?)"
        r"const handleServiceClick =",
        src,
        re.S,
    )
    assert match, "Forecast-Modus-Hilfswerte fehlen oder stehen nicht vor dem Rendern"
    return match.group(0)


def test_dashboard_uses_ml_blocked_reason():
    src = _src(DASHBOARD)
    block = _forecast_mode_block()

    assert "current_runtime_mode" in src, "Dashboard wertet current_runtime_mode nicht aus"
    assert "historical_24h_usage" in src, "Dashboard trennt historische Nutzung nicht vom Runtime-Status"
    assert "value={forecastModeValue}" in src, \
        "Forecast-Modus-Card muss den berechneten, blockstatusbewussten Wert nutzen"
    assert "value={forecastStats.active_mode" not in src, \
        "Forecast-Modus-Card nutzt weiterhin direkt active_mode"


def test_dashboard_shows_fallback_when_ml_blocked():
    block = _forecast_mode_block()

    for required in (
        "mlBlocked",
        "currentRuntimeMode",
        "Fallback-Grund",
        "border-yellow",
        "📐 Aktueller Modus: Fallback aktiv",
        "Historie 24h",
    ):
        assert required in block, f"{required!r} fehlt im Forecast-Modus-Block"


def test_progress_still_uses_forecast_stats():
    src = _src(PROGRESS)

    assert "/api/forecast_stats" in src, "Progress nutzt forecast_stats nicht mehr"
    assert "ml_blocked_reason" in src, "Progress wertet ml_blocked_reason nicht mehr aus"
    assert "const mlActive" in src and "fcStats.ml_blocked_reason == null" in src, \
        "Progress muss den aktiven Modus weiterhin ueber ml_blocked_reason bestimmen"
