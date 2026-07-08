"""
B324: hail_warning wurde ausschliesslich aus der zu strengen, multiplikativen
_compute_hail_prob()-Formel abgeleitet. Das bereits vorhandene, SHIP-basierte
hail_prob2 (compute_convective_indices.py) wurde nie fuer die Warnentscheidung
ausgewertet, obwohl sein eigener Docstring es explizit dafuer vorsieht
("kompatibel mit HAIL_WARN_THRESHOLD"). Diese Tests belegen den Bug (alte
Formel allein haette nicht gewarnt) und verifizieren die neue Fusionslogik.
"""
import ast
from pathlib import Path


def _load_functions(path: str, names):
    module = ast.parse(Path(path).read_text(encoding="utf-8"))
    wanted = set(names)
    found = [n for n in module.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    assert len(found) == len(wanted), f"Nicht alle Funktionen gefunden: {wanted - {n.name for n in found}}"
    code = compile(ast.Module(body=found, type_ignores=[]), path, "exec")
    ns = {}
    exec(code, ns)
    return ns


def test_hail_warning_triggers_via_ship_based_hail_prob2_alone():
    """Belegt den Bug: die alte Formel allein bleibt weit unter dem Schwellwert,
    obwohl hail_prob2 (SHIP) klar auf Hagel hindeutet - die Fusion muss trotzdem warnen."""
    ns = _load_functions("main.py", ["_compute_hail_prob", "_compute_hail_warning"])
    ns["HAIL_WARN_THRESHOLD"] = 0.45
    ns["HAIL_VIOLET_RATIO_SATURATION"] = 0.10
    obj = {
        "core_ratio": 0.10,
        "cape": 400.0,
        "arome_fl_height": 3900.0,   # realistischer Kaerntner Sommerwert, > 3000 m
        "hail_prob2": 0.70,
    }
    hp, hp_eff, warn = ns["_compute_hail_warning"](obj)
    assert hp < 0.45, "Alte Formel haette hier (Bug-Fall) NICHT gewarnt"
    assert hp_eff == 0.70
    assert warn is True


def test_hail_warning_still_triggers_via_legacy_formula_alone():
    """Regression: starke Zellen, die schon die alte Formel korrekt erkannte,
    muessen weiterhin warnen."""
    ns = _load_functions("main.py", ["_compute_hail_prob", "_compute_hail_warning"])
    ns["HAIL_WARN_THRESHOLD"] = 0.45
    ns["HAIL_VIOLET_RATIO_SATURATION"] = 0.10
    obj = {
        "core_ratio": 0.60,
        "cape": 1600.0,
        "arome_fl_height": 2800.0,
        "hail_prob2": 0.05,
    }
    hp, hp_eff, warn = ns["_compute_hail_warning"](obj)
    assert hp >= 0.45
    assert hp_eff == hp
    assert warn is True


def test_hail_warning_false_when_both_metrics_low():
    ns = _load_functions("main.py", ["_compute_hail_prob", "_compute_hail_warning"])
    ns["HAIL_WARN_THRESHOLD"] = 0.45
    ns["HAIL_VIOLET_RATIO_SATURATION"] = 0.10
    obj = {"core_ratio": 0.10, "cape": 300.0, "arome_fl_height": 4200.0, "hail_prob2": 0.10}
    hp, hp_eff, warn = ns["_compute_hail_warning"](obj)
    assert warn is False


def test_hail_prob_ml_feature_unchanged_for_backward_compat():
    """B324: hail_prob (ML_CELL_FEATURES) darf sich NICHT aendern - sonst
    waere Retraining aller bestehenden Modelle noetig."""
    ns = _load_functions("main.py", ["_compute_hail_prob", "_compute_hail_warning"])
    obj = {"core_ratio": 0.5, "cape": 1000.0, "arome_fl_height": 3200.0, "hail_prob2": 0.9}
    hp_direct = ns["_compute_hail_prob"](obj)
    ns["HAIL_WARN_THRESHOLD"] = 0.45
    ns["HAIL_VIOLET_RATIO_SATURATION"] = 0.10
    hp, hp_eff, warn = ns["_compute_hail_warning"](obj)
    assert hp == hp_direct


def test_suppress_inactive_rain_resets_hail_prob_effective_main():
    ns = _load_functions("main.py", ["_suppress_inactive_rain_warning_badges"])
    obj = {
        "tracking_state": "inactive_rain",
        "hail_warning": True,
        "hail_prob": 0.9,
        "hail_prob_effective": 0.95,
        "stationary_marker": True,
        "stationary_risk": 0.8,
    }
    ns["_suppress_inactive_rain_warning_badges"](obj)
    assert obj["hail_prob_effective"] == 0.0
    assert obj["hail_warning"] is False


def test_suppress_inactive_rain_resets_hail_prob_effective_object_tracking():
    ns = _load_functions("object_tracking.py", ["_suppress_inactive_rain_warning_fields"])
    obj = {
        "tracking_state": "inactive_rain",
        "silent_tracking": True,
        "hail_warning": True,
        "hail_prob": 0.9,
        "hail_prob_effective": 0.95,
        "stationary_marker": True,
        "stationary_risk": 0.8,
    }
    ns["_suppress_inactive_rain_warning_fields"](obj)
    assert obj["hail_prob_effective"] == 0.0


def test_main_loop_uses_new_fusion_function():
    """Statische Pruefung: der operative Hagel-Block in main.py muss
    _compute_hail_warning() aufrufen statt weiterhin nur _compute_hail_prob()
    fuer die Warnentscheidung zu verwenden."""
    text = Path("main.py").read_text(encoding="utf-8")
    assert "_hp, _hp_eff, _hw = _compute_hail_warning(_obj)" in text
    assert '_obj["hail_prob_effective"] = _hp_eff' in text
    assert '_obj["hail_warning"]        = _hw' in text
