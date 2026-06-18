from pathlib import Path


def test_map_popups_show_compact_core_label():
    for path in [Path("frontend/src/pages/MapView.jsx"), Path("frontend/src/pages/MapFullscreen.jsx")]:
        text = path.read_text(encoding="utf-8")
        assert "kompakt" in text
        assert "Kern:" in text
        assert "konzentriert sich" in text
        assert "Fläche:" in text
