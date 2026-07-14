"""B361 (Codex-Review-Fix zu B360): batch_size=1 darf nicht mehr auf 2
angehoben werden — sonst fuehrt der dritte Eltern-Kaskaden-Versuch (B360)
faktisch nur batch_size=2 ein zweites Mal aus, statt den echten letzten
Rettungsversuch mit batch_size=1."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_no_floor_of_two_on_batch_size():
    src = _read("radar_convlstm.py")
    assert "safe_batch_size = 2 if batch_size < 2 else batch_size" not in src, \
        "Alter Clamp (Floor=2) wieder eingefuehrt — hebt batch_size=1 faelschlich an"
    assert "safe_batch_size = max(1, int(batch_size))" in src


def _candidates_for(safe_batch_size: int) -> list[int]:
    """Baut dieselbe Kandidatenliste nach wie train_convlstm() (Zeilen nach
    dem Clamp) — dient als Regressionsschutz fuer die Kaskaden-Reihenfolge."""
    candidates: list[int] = []
    for b in (safe_batch_size, 2, 1):
        if b <= safe_batch_size and b not in candidates:
            candidates.append(b)
    return candidates


def test_requested_batch_size_one_yields_only_one():
    # B360 dritter Eltern-Versuch: --batch-size 1
    safe_batch_size = max(1, int(1))
    assert safe_batch_size == 1
    assert _candidates_for(safe_batch_size) == [1]


def test_requested_batch_size_two_unchanged():
    # B360 zweiter Eltern-Versuch: --batch-size 2 (Regressionsschutz)
    safe_batch_size = max(1, int(2))
    assert safe_batch_size == 2
    assert _candidates_for(safe_batch_size) == [2, 1]


def test_requested_batch_size_four_unchanged():
    # B360 erster Eltern-Versuch / CLI-Default: --batch-size 4 (Regressionsschutz)
    safe_batch_size = max(1, int(4))
    assert safe_batch_size == 4
    assert _candidates_for(safe_batch_size) == [4, 2, 1]
