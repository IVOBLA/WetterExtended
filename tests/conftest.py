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



def _ensure_real_debug_utils():
    """Stellt sicher, dass sys.modules["debug_utils"] kein Test-Stub ist."""
    mod = sys.modules.get("debug_utils")
    if mod is not None and (
        _is_module_impostor(mod)
        or not hasattr(mod, "api_call_summary")
        or not hasattr(mod, "api_health_summary")
        or not hasattr(mod, "log_api_failure")
    ):
        del sys.modules["debug_utils"]
    return importlib.import_module("debug_utils")


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
        debug_utils = _ensure_real_debug_utils()
    except Exception:
        yield
        return
    monkeypatch.setattr(
        debug_utils, "_API_HEALTH_FILE",
        str(tmp_path / "api_health.jsonl"), raising=False,
    )
    yield


@pytest.fixture(autouse=True)
def _isolate_evaluation_writes(tmp_path, monkeypatch):
    """
    B216: Verhindert, dass Tests in die ECHTE train_data/evaluation/ schreiben
    (forecast_error_details.jsonl, accuracy_history.jsonl). Klasse B127/B129/B179:
    test_accuracy_tracker_horizon_mode ruft evaluate_for_horizon() auf, das via
    _jsonl_append(DETAILS_FILE, rec) synthetische cell-1-Records in die echte Datei
    schrieb (bei jedem install.sh-Phase-9-Lauf). Diese Fixture lenkt den Schreibpfad
    pro Test nach tmp/train_data/evaluation, ohne das evaluation-Verzeichnis vorab anzulegen:
      (a) SAVE_PATHS['evaluation'] — greift auch bei Re-Import von accuracy_tracker,
      (b) falls accuracy_tracker bereits importiert ist, dessen Modul-Konstanten direkt.
    """
    train_data = tmp_path / "train_data"
    train_data.mkdir(parents=True, exist_ok=True)
    ev = train_data / "evaluation"
    try:
        import config
        monkeypatch.setitem(config.SAVE_PATHS, "evaluation", str(ev) + "/")
    except Exception:
        pass
    at = sys.modules.get("accuracy_tracker")
    if at is not None:
        monkeypatch.setattr(at, "EVAL_DIR", str(ev), raising=False)
        monkeypatch.setattr(at, "DETAILS_FILE", str(ev / "forecast_error_details.jsonl"), raising=False)
        monkeypatch.setattr(at, "HISTORY_FILE", str(ev / "accuracy_history.jsonl"), raising=False)
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
