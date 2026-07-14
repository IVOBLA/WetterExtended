"""B378: Die Herkunft einer Zelle muss über Frames erhalten bleiben."""
import ast
from pathlib import Path


def _load_function(path: str, name: str):
    module = ast.parse(Path(path).read_text(encoding="utf-8"))
    fn = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == name)
    code = compile(ast.Module(body=[fn], type_ignores=[]), path, "exec")
    ns = {}
    exec(code, ns)
    return ns[name]


_resolve_origin_type = _load_function("object_tracking.py", "_resolve_origin_type")


def test_merge_event_frame_sets_origin():
    assert _resolve_origin_type("merged", None) == "created_by_merge"


def test_split_event_frame_sets_origin():
    assert _resolve_origin_type("split", None) == "created_by_split"


def test_new_cell_is_new():
    assert _resolve_origin_type("new", None) == "new"


def test_continued_inherits_merge_origin():
    """Kernregression: ab Frame 2 ist lineage 'continued' — die Herkunft muss bleiben."""
    prev = {"origin_type": "created_by_merge"}
    assert _resolve_origin_type("continued", prev) == "created_by_merge"


def test_continued_inherits_split_origin():
    prev = {"origin_type": "created_by_split"}
    assert _resolve_origin_type("continued", prev) == "created_by_split"


def test_origin_survives_long_merge_series():
    """55-Minuten-Verbund (11 Frames): die Herkunft darf nie auf 'new' zurückfallen."""
    origin = _resolve_origin_type("merged", None)
    for _ in range(11):
        origin = _resolve_origin_type("continued", {"origin_type": origin})
    assert origin == "created_by_merge"


def test_continued_without_previous_defaults_to_new():
    assert _resolve_origin_type("continued", None) == "new"


def test_invalid_previous_origin_defaults_to_new():
    assert _resolve_origin_type("continued", {"origin_type": "garbage"}) == "new"


def test_non_dict_previous_is_safe():
    assert _resolve_origin_type("continued", "not-a-dict") == "new"


def test_split_after_merge_overrides_origin():
    """Ein neues Ereignis setzt die Herkunft neu — kein Erbe des alten Zustands."""
    prev = {"origin_type": "created_by_merge"}
    assert _resolve_origin_type("split", prev) == "created_by_split"
