# tests/conftest.py
"""
B96: sys.modules-Schutz — numpy/pandas vor der Test-Sammlung korrekt laden.

Hintergrund: test_eumetview_parser.py setzte bisher
  sys.modules.setdefault("numpy", types.SimpleNamespace(ndarray=object))
auf Modulebene. Da numpy beim Sammeln dieser Datei noch nicht in
sys.modules war, blieb dieser Mock haften und korrumpierte rasterio-
und pandas-Imports in allen nachfolgenden Test-Dateien (Phase-9-Fehler).

pytest_configure läuft VOR der Test-Sammlung und stellt sicher, dass
sys.modules["numpy"] echte kritische Module enthält, bevor irgendeine
Test-Datei einen SimpleNamespace-Mock setzen kann.
"""

import sys
import types
import importlib

import pytest


def pytest_configure(config):
    """Lädt kritische Pakete frühzeitig — vor jeder Test-Datei-Sammlung."""
    _preload_critical_modules()


def _is_module_impostor(module):
    """Erkennt einfache Test-Doubles, die echte Imports blockieren würden."""
    return isinstance(module, types.SimpleNamespace) or (
        isinstance(module, types.ModuleType) and getattr(module, "__spec__", None) is None
    )


def _preload_critical_modules():
    """
    Entfernt SimpleNamespace-/Fake-Impostoren und lädt echte Module nach.
    Gilt für numpy, pandas, cv2 und shapely — diese Module dürfen kein
    Mock-Objekt sein, weil spätere Tests echte Submodule daraus importieren.
    B160: zusätzlich requests + http_retry — test_eumetview_parser.py stubte diese
    früher per sys.modules.setdefault(SimpleNamespace) und korrumpierte so
    test_b149_*/test_b151_*/test_nowcast_out_of_coverage_b131. requests vor http_retry,
    weil http_retry beim Import eine requests.Session aufbaut.
    """
    for name in ("numpy", "pandas", "cv2", "shapely", "shapely.geometry", "shapely.ops",
                 "requests", "http_retry"):
        if name in sys.modules and _is_module_impostor(sys.modules[name]):
            del sys.modules[name]
        try:
            importlib.import_module(name)
        except Exception:
            pass  # Nicht verfügbar/kaputt → pytest.importorskip bzw. Modul-Guards zuständig


@pytest.fixture(autouse=True)
def _isolate_api_health_log(tmp_path, monkeypatch):
    """
    B129: Tests, die Fehlerpfade simulieren (Outlook/Circuit-Breaker), rufen
    log_api_failure() auf. Bisher schrieben sie in die ECHTE
    train_data/evaluation/api_health.jsonl -> synthetische Eintraege
    ('RuntimeError: x', 'ConnectionError: down', ...) verschmutzten das
    Admin-Dashboard nach jedem install.sh-Phase-9-Lauf. Diese Fixture lenkt den
    Schreibpfad (Modul-Konstante debug_utils._API_HEALTH_FILE) pro Test in ein
    tmp-Verzeichnis um.
    """
    try:
        import debug_utils
    except Exception:
        yield
        return
    monkeypatch.setattr(
        debug_utils, "_API_HEALTH_FILE",
        str(tmp_path / "api_health.jsonl"), raising=False,
    )
    yield


def _drop_numpy_contaminated_modules():
    """
    B127: Entfernt ein mit numpy-Stub kontaminiertes `prediction`/`model_training`
    aus sys.modules. Tests wie test_lstm_feature_mismatch.py importieren `prediction`
    mit einem numpy-Stub (asarray liefert die Eingabe unverändert) und stellen das
    gecachte Modul nicht wieder her. Erkennung: echtes numpy hat `ndarray`, die
    Stubs nicht. So importiert der nächste Test das Modul wieder mit echtem numpy.
    """
    for _name in ("prediction", "model_training"):
        _mod = sys.modules.get(_name)
        if _mod is None:
            continue
        _np = getattr(_mod, "np", None)
        if _np is not None and not hasattr(_np, "ndarray"):
            del sys.modules[_name]


@pytest.fixture(autouse=True)
def _restore_numpy_dependent_modules():
    """B127: nach jedem Test kontaminierte numpy-abhängige Module bereinigen."""
    yield
    _drop_numpy_contaminated_modules()
