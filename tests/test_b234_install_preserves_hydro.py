"""B234 — Upgrade (rsync --delete im LOCAL/ZIP-Modus) darf train_data/hydro/ nicht löschen.

Statischer Vertrag: der rsync-Block in install.sh muss train_data/hydro/ ebenso
ausschließen wie statistics/dem/cell_filters/cell_lineage, sonst gehen
Impact-Historie und generierte Hydro-Geodaten beim Upgrade verloren.
"""

import re
from pathlib import Path

INSTALL = Path(__file__).resolve().parent.parent / "install.sh"


def _rsync_block(text: str) -> str:
    # Block ab 'rsync -a --delete' bis zur Quell/Ziel-Zeile (zusammenhängende \-Fortsetzung).
    m = re.search(r"rsync -a --delete.*?\"\$LOCAL_SOURCE/\" \"\$TARGET/\"", text, re.S)
    assert m, "rsync-Block in install.sh nicht gefunden"
    return m.group(0)


def test_rsync_excludes_hydro():
    block = _rsync_block(INSTALL.read_text(encoding="utf-8"))
    assert "--exclude=/train_data/hydro/" in block, "train_data/hydro/ wird vom rsync nicht geschützt"


def test_rsync_still_excludes_other_longterm_data():
    block = _rsync_block(INSTALL.read_text(encoding="utf-8"))
    for needle in (
        "--exclude=/.env",
        "--exclude=/users.db",
        "--exclude=/train_data/runtime_overrides.json",
        "--exclude=/train_data/statistics/",
        "--exclude=/train_data/dem/",
        "--exclude=/train_data/cell_filters/",
        "--exclude=/train_data/cell_lineage/",
    ):
        assert needle in block, f"Regression: {needle} fehlt im rsync-Block"
