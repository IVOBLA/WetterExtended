"""B238 — Hydro-Admin-Buttons: Spinner/Disabled, Inline-Feedback, Backend-Fehlertext
und Polling des asynchronen Static-Imports (haengt von B236 ab)."""

from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "frontend" / "src" / "pages" / "Configuration.jsx"


def _src():
    return SRC.read_text(encoding="utf-8")


def test_busy_state_and_handlers_present():
    s = _src()
    assert "const [hydroBusy, setHydroBusy] = useState('')" in s
    assert "const [hydroMsg, setHydroMsg] = useState('')" in s
    assert "async function runHydroAction(" in s
    assert "async function pollHydroImport(" in s


def test_buttons_disabled_and_progress_label():
    s = _src()
    assert s.count("disabled={!!hydroBusy}") >= 3
    assert "runHydroAction('reload-static', '/api/hydro/reload-static'" in s
    assert "eigener Prozess" in s


def test_polls_async_import_and_surfaces_backend_error():
    s = _src()
    assert "/api/hydro/import-status" in s
    assert "(started === 'started' || started === 'already_running')" in s
    assert "e?.payload?.error" in s
    assert "(hydroBusy || hydroMsg)" in s
    assert ".then(() => setMsg('✅ Live-Hydro geladen.'))" not in s
