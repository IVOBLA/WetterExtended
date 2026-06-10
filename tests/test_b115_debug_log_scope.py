"""B115: update_tracking_memory darf kein UnboundLocalError für debug_log mehr werfen.

Statischer Scope-Check (ohne numpy/cv2-Abhängigkeit): die Funktion
update_tracking_memory darf KEINEN funktionslokalen `from debug_utils import
debug_log` enthalten, weil dieser debug_log für die gesamte Funktion zur
lokalen Variable macht und damit frühere debug_log-Aufrufe crashen lässt.
"""
import ast
import os

_SRC = os.path.join(os.path.dirname(__file__), "..", "object_tracking.py")


def _function_node(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def test_module_level_debug_log_import_present():
    tree = ast.parse(open(_SRC, encoding="utf-8").read())
    found = False
    for node in tree.body:  # nur Modulebene
        if isinstance(node, ast.ImportFrom) and node.module == "debug_utils":
            if any(a.name == "debug_log" for a in node.names):
                found = True
    assert found, "debug_log muss am Modulkopf global importiert sein"


def test_update_tracking_memory_has_no_local_debug_log_import():
    tree = ast.parse(open(_SRC, encoding="utf-8").read())
    fn = _function_node(tree, "update_tracking_memory")
    assert fn is not None, "update_tracking_memory nicht gefunden"
    for node in ast.walk(fn):
        if isinstance(node, ast.ImportFrom) and node.module == "debug_utils":
            names = [a.name for a in node.names]
            assert "debug_log" not in names, (
                "B115: funktionslokaler 'from debug_utils import debug_log' in "
                "update_tracking_memory gefunden → verursacht UnboundLocalError"
            )
