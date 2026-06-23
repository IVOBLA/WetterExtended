from pathlib import Path


def test_ir_popup_labels_and_clear_logic_present():
    for rel in ("frontend/src/pages/MapView.jsx", "frontend/src/pages/MapFullscreen.jsx"):
        src = Path(rel).read_text()
        assert "Erste Ortung:" in src
        assert "Letzte Ortung:" in src
        assert "Datenalter:" in src
        assert "setIrCells([])" in src
        assert "setInterval(loadIrCells, 60000)" in src
        assert "Number(o.missing ?? 0) === 0" in src
