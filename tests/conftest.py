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


def _preload_critical_modules():
    """
    Entfernt SimpleNamespace-Impostoren und lädt echte Module nach.
    Gilt für numpy, pandas und cv2 — diese Module dürfen kein
    SimpleNamespace-Mock-Objekt sein.
    """
    for name in ("numpy", "pandas", "cv2"):
        if name in sys.modules and isinstance(sys.modules[name], types.SimpleNamespace):
            del sys.modules[name]
        try:
            importlib.import_module(name)
        except Exception:
            pass  # Nicht verfügbar/kaputt → pytest.importorskip bzw. Modul-Guards zuständig
