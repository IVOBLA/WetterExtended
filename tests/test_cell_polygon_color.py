from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
MAP_VIEW = ROOT / "frontend" / "src" / "pages" / "MapView.jsx"
MAP_FULLSCREEN = ROOT / "frontend" / "src" / "pages" / "MapFullscreen.jsx"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _cell_stroke_body(source: str) -> str:
    match = re.search(r"function\s+cellStroke\s*\([^)]*\)\s*\{(?P<body>.*?)\n\}", source, re.S)
    assert match, "cellStroke function not found"
    return match.group("body")


def test_mapview_defines_unified_cell_polygon_color():
    source = _read(MAP_VIEW)

    assert "const CELL_POLYGON_COLOR = '#0b1f5e'" in source
    assert "const CELL_POLYGON_FILL_OPACITY = 0.25" in source


def test_mapfullscreen_defines_unified_cell_polygon_color():
    source = _read(MAP_FULLSCREEN)

    assert "const CELL_POLYGON_COLOR = '#0b1f5e'" in source
    assert "const CELL_POLYGON_FILL_OPACITY = 0.25" in source


def test_current_cell_polygons_no_longer_use_orange_fill():
    for path in (MAP_VIEW, MAP_FULLSCREEN):
        source = _read(path)

        assert "'#ff8800'" not in source
        assert '"#ff8800"' not in source
        assert "fillColor:CELL_POLYGON_COLOR" in source or "fillColor: CELL_POLYGON_COLOR" in source


def test_cell_stroke_no_longer_uses_lineage_color_for_polygon_color():
    for path in (MAP_VIEW, MAP_FULLSCREEN):
        source = _read(path)
        body = _cell_stroke_body(source)

        assert "lineageColor" not in body
        assert "color: CELL_POLYGON_COLOR" in body
        assert "dashArray: '10,6'" in body
        assert "dashArray: '4,4'" in body


def test_forecast_ghost_colors_remain_available_in_mapview():
    source = _read(MAP_VIEW)

    assert "#6a1b9a" in source
    assert "#9c27b0" in source


KMZ_EXPORT = ROOT / "kmz_export.py"


def test_kmz_current_cell_contours_use_unified_cell_polygon_color():
    source = _read(KMZ_EXPORT)

    assert 'CELL_POLYGON_COLOR = "#0b1f5e"' in source
    current_layer = source.split("# ── Layer 2/3: Forecast-Pfeile", 1)[0]
    assert '_hex_to_kml_color(CELL_POLYGON_COLOR)' in current_layer
    assert '_hex_to_kml_color(CELL_POLYGON_COLOR, alpha=60)' in current_layer
    assert '_hex_to_kml_color("#dc2626")' not in current_layer
