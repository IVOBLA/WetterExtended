import os
import sys
import importlib
import importlib.util
from config import SAVE_PATHS

evaluate_on_recent = importlib.import_module("model_training").evaluate_on_recent

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


def compare(version_a, version_b):
    dir_a = os.path.join(_base_dir(), version_a)
    dir_b = os.path.join(_base_dir(), version_b)
    if not os.path.isdir(dir_a) or not os.path.isdir(dir_b):
        raise SystemExit("Beide Versionen müssen existieren.")
    eval_a = evaluate_on_recent(dir_a)
    eval_b = evaluate_on_recent(dir_b)
    print("Vergleich MAE (kleiner ist besser)")
    print(f"{'Version':<28} {'Samples':>8} {'MAE total':>12} {'h10':>10} {'h20':>10} {'h30':>10}")
    for version, metrics in [(version_a, eval_a), (version_b, eval_b)]:
        mae_by_h = metrics.get("mae_by_horizon", {})
        print(
            f"{version:<28} {metrics.get('samples', 0):>8} {metrics.get('mae_total', float('inf')):>12.4f} "
            f"{mae_by_h.get('10', float('nan')):>10.4f} {mae_by_h.get('20', float('nan')):>10.4f} {mae_by_h.get('30', float('nan')):>10.4f}"
        )


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in {"list", "rollback", "compare"}:
        print("Usage: python3 models_rollback.py list | python3 models_rollback.py rollback <id> | python3 models_rollback.py compare <id1> <id2>")
        raise SystemExit(1)
    if sys.argv[1] == "list":
        list_versions()
    elif sys.argv[1] == "rollback":
        if len(sys.argv) < 3:
            raise SystemExit("Bitte Versions-ID angeben.")
        rollback(sys.argv[2])
    else:
        if len(sys.argv) < 4:
            raise SystemExit("Bitte zwei Versions-IDs angeben.")
        compare(sys.argv[2], sys.argv[3])
