import ast
from pathlib import Path


def _load_function(path: str, name: str):
    module = ast.parse(Path(path).read_text(encoding="utf-8"))
    fn = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == name)
    code = compile(ast.Module(body=[fn], type_ignores=[]), path, "exec")
    ns = {}
    exec(code, ns)
    return ns[name]


def test_object_tracking_clears_inactive_rain_warning_fields():
    suppress = _load_function("object_tracking.py", "_suppress_inactive_rain_warning_fields")
    obj = {
        "tracking_state": "inactive_rain",
        "silent_tracking": True,
        "hail_warning": True,
        "stationary_marker": True,
        "hail_prob": 0.91,
        "stationary_risk": 0.88,
    }

    assert suppress(obj) is obj
    assert obj["hail_warning"] is False
    assert obj["stationary_marker"] is False
    assert obj["hail_prob"] == 0.0
    assert obj["stationary_risk"] == 0.0


def test_main_suppresses_inactive_rain_badges_but_keeps_active_cells():
    suppress = _load_function("main.py", "_suppress_inactive_rain_warning_badges")
    inactive = {
        "tracking_state": "inactive_rain",
        "hail_warning": True,
        "stationary_marker": True,
        "hail_prob": 0.75,
        "stationary_risk": 0.8,
    }
    active = {
        "tracking_state": "active",
        "hail_warning": True,
        "stationary_marker": True,
        "hail_prob": 0.75,
        "stationary_risk": 0.8,
    }

    assert suppress(inactive) is inactive
    assert inactive["hail_warning"] is False
    assert inactive["stationary_marker"] is False
    assert inactive["hail_prob"] == 0.0
    assert inactive["stationary_risk"] == 0.0

    suppress(active)
    assert active["hail_warning"] is True
    assert active["stationary_marker"] is True
    assert active["hail_prob"] == 0.75
    assert active["stationary_risk"] == 0.8


def test_main_inactive_rain_branch_skips_hail_recalculation():
    text = Path("main.py").read_text(encoding="utf-8")
    assert 'if _obj.get("tracking_state") == "inactive_rain" or _obj.get("silent_tracking") is True:' in text
    branch_start = text.index('if _obj.get("tracking_state") == "inactive_rain" or _obj.get("silent_tracking") is True:')
    hail_start = text.index('_hp = _compute_hail_prob(_obj)', branch_start)
    branch = text[branch_start:hail_start]
    assert '_suppress_inactive_rain_warning_badges(_obj)' in branch
    assert 'continue' in branch
