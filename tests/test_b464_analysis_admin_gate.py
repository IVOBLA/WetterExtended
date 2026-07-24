"""B464 (Codex-Review zu P80): Betriebsart und Runner-Konfiguration sind admin-pflichtig.

_jwt_auth_check leitet Schreibrechte ausschliesslich aus _ADMIN_WRITE_PREFIXES ab.
Standen die neuen Praefixe nur in _SENSITIVE_READ_PREFIXES, konnte ein operator-Token
per POST die taegliche Analyse umstellen — das widerspricht der Rollentrennung
(operator bedient, admin konfiguriert).
"""
import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app.py"


def _tuple_entries(name):
    tree = ast.parse(APP.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) == name for t in node.targets
        ):
            return [
                e.value for e in node.value.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)
            ]
    raise AssertionError(f"{name} nicht gefunden")


def test_analysis_mode_requires_admin_for_writes():
    assert "/api/analysis_mode" in _tuple_entries("_ADMIN_WRITE_PREFIXES")


def test_local_analysis_requires_admin_for_writes():
    assert "/api/local_analysis" in _tuple_entries("_ADMIN_WRITE_PREFIXES")


def test_both_prefixes_still_require_login_for_reads():
    read = _tuple_entries("_SENSITIVE_READ_PREFIXES")
    assert "/api/analysis_mode" in read
    assert "/api/local_analysis" in read


def test_admin_list_is_the_only_source_of_write_rights():
    """Regression: wer hier etwas ergaenzt, muss auch _ADMIN_WRITE_PREFIXES pflegen."""
    src = APP.read_text(encoding="utf-8")
    assert "is_admin_path = any(request.path.startswith(p) for p in _ADMIN_WRITE_PREFIXES)" in src


def test_manual_run_route_is_admin_gated():
    """POST /api/system/run_job/... faellt unter /api/system/."""
    assert "/api/system/" in _tuple_entries("_ADMIN_WRITE_PREFIXES")
