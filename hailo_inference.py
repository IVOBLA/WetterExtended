import os
from typing import Optional

try:
    from debug_utils import debug_log
except Exception:
    def debug_log(msg):
        print(msg)

HEF_DIR = "models/hailo"


class HailoBackend:
    def __init__(self):
        self.available = False
        self.HEF = None
        self.VDevice = None
        try:
            from hailo_platform import HEF, VDevice  # type: ignore
            self.HEF = HEF
            self.VDevice = VDevice
            self.available = True
        except Exception:
            pass

    def is_available(self) -> bool:
        return self.available

    def load_hef(self, hef_path: str):
        if not self.available:
            return None
        if not os.path.exists(hef_path):
            debug_log(f"[HAILO] HEF nicht gefunden: {hef_path}")
            return None
        try:
            return self.HEF(hef_path)
        except Exception as exc:
            debug_log(f"[HAILO] Fehler beim Laden von {hef_path}: {exc}")
            return None


_backend: Optional[HailoBackend] = None


def get_backend() -> HailoBackend:
    global _backend
    if _backend is None:
        _backend = HailoBackend()
    return _backend


def hef_path_for(model_name: str) -> str:
    return os.path.join(HEF_DIR, f"{model_name}.hef")


def predict_with_fallback(model_name: str, fallback_callable, *args, **kwargs):
    """Versucht Hailo-Inferenz, fällt bei Fehler auf CPU-Callable zurück."""
    backend = get_backend()
    if not backend.is_available():
        return fallback_callable(*args, **kwargs)
    hef = backend.load_hef(hef_path_for(model_name))
    if hef is None:
        return fallback_callable(*args, **kwargs)
    debug_log(f"[HAILO] Inferenz für {model_name} angefordert (TODO: VDevice-Pipeline)")
    return fallback_callable(*args, **kwargs)


if __name__ == "__main__":
    backend = get_backend()
    print(f"Hailo verfügbar: {backend.is_available()}")
