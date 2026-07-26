"""B475 — Download-Route fuer das Ergebnis der lokalen Analyse."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
JSX = ROOT / "frontend/src/pages/AiSuggestions.jsx"
HB = ROOT / "docs/WetterExtended_Benutzerhandbuch.md"


def _src():
    return APP.read_text(encoding="utf-8")


def _body(name):
    return _src().split(f"def {name}", 1)[1].split("@app.route", 1)[0]


def test_route_exists():
    assert '@app.route("/api/local_analysis/result")' in _src()


def test_handler_defined():
    names = {n.name for n in ast.walk(ast.parse(_src()))
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "api_local_analysis_result" in names


def test_missing_file_returns_404():
    b = _body("api_local_analysis_result")
    assert "is_file()" in b and "404" in b


def test_serves_as_attachment():
    b = _body("api_local_analysis_result")
    assert "as_attachment=True" in b and 'download_name="analysis_result.json"' in b


def test_route_under_sensitive_prefix():
    prefixes = _src().split("_SENSITIVE_READ_PREFIXES = (", 1)[1].split(")", 1)[0]
    assert '"/api/local_analysis"' in prefixes


def test_frontend_uses_download_helper_and_button():
    j = JSX.read_text(encoding="utf-8")
    assert "downloadLaResult" in j
    assert "api.download('/api/local_analysis/result')" in j
    assert "Bericht herunterladen" in j


def test_handbook_documents_download():
    assert "Bericht herunterladen" in HB.read_text(encoding="utf-8")
