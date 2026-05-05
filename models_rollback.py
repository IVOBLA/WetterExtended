import os
import sys
from config import SAVE_PATHS


def _base_dir():
    return SAVE_PATHS["models"]


def _current_link():
    return os.path.join(_base_dir(), "current")


def list_versions():
    base = _base_dir()
    versions = sorted([v for v in os.listdir(base) if v.startswith("v_") and os.path.isdir(os.path.join(base, v))]) if os.path.isdir(base) else []
    current = None
    if os.path.islink(_current_link()):
        current = os.path.basename(os.path.realpath(_current_link()))
    for v in versions:
        marker = "*" if v == current else " "
        print(f"{marker} {v}")


def rollback(version_id):
    target = os.path.join(_base_dir(), version_id)
    if not os.path.isdir(target):
        raise SystemExit(f"Version nicht gefunden: {version_id}")
    tmp = os.path.join(_base_dir(), ".current_tmp")
    if os.path.lexists(tmp):
        os.remove(tmp)
    os.symlink(os.path.relpath(target, _base_dir()), tmp)
    os.replace(tmp, _current_link())
    print(f"Rollback auf {version_id} durchgeführt.")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in {"list", "rollback"}:
        print("Usage: python3 models_rollback.py list | python3 models_rollback.py rollback <id>")
        raise SystemExit(1)
    if sys.argv[1] == "list":
        list_versions()
    else:
        if len(sys.argv) < 3:
            raise SystemExit("Bitte Versions-ID angeben.")
        rollback(sys.argv[2])
