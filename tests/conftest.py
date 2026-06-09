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
    """
    for name in ("numpy", "pandas", "cv2", "shapely", "shapely.geometry", "shapely.ops"):
        if name in sys.modules and _is_module_impostor(sys.modules[name]):
            del sys.modules[name]
        try:
            importlib.import_module(name)
        except Exception:
            pass  # Nicht verfügbar/kaputt → pytest.importorskip bzw. Modul-Guards zuständig
