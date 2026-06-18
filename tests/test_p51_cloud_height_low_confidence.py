"""P51: warm_top_height_msl liefert eine physikalisch sinnvolle Höhe (low-confidence),
sodass die Wolkenhöhe für konvektive Zellen mit warmem IR-Top IMMER befüllt ist."""
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_warm_top_height_msl():
    """Lädt nur den Helper, ohne die Runtime-Abhängigkeiten des Moduls zu importieren."""
    tree = ast.parse((ROOT / "cloud_height_from_eumetview.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "warm_top_height_msl":
            module = ast.Module(body=[node], type_ignores=[])
            ast.fix_missing_locations(module)
            namespace = {}
            exec(compile(module, "cloud_height_from_eumetview.py", "exec"), namespace)
            return namespace["warm_top_height_msl"]
    raise AssertionError("warm_top_height_msl nicht gefunden")


def test_warm_top_height_from_bt():
    warm_top_height_msl = _load_warm_top_height_msl()
    # T_surface=290.15 K, bt=282.4 K, lapse=0.0065 K/m, alt=600 m
    # (290.15-282.4)/0.0065 + 600 = 1192.3 + 600 ≈ 1792 m
    h = warm_top_height_msl(282.4, 290.15, 0.0065, 600.0)
    assert 1700.0 < h < 1900.0, f"unerwartete Höhe: {h}"


def test_warm_top_floor_at_terrain():
    warm_top_height_msl = _load_warm_top_height_msl()
    # bt >= T_surface → Formel würde < altitude_m liefern → auf altitude_m geklemmt
    h = warm_top_height_msl(300.0, 290.15, 0.0065, 600.0)
    assert h == 600.0, f"Untergrenze nicht eingehalten: {h}"
