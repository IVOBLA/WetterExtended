from pathlib import Path


def test_map_views_render_inactive_rain_and_reactivated_status():
    for path in [Path('frontend/src/pages/MapView.jsx'), Path('frontend/src/pages/MapFullscreen.jsx')]:
        text = path.read_text(encoding='utf-8')
        assert "trackingState === 'inactive_rain'" in text
        assert "dashArray: '7,6'" in text
        assert "fillOpacity: 0.10" in text
        assert "Status: stille Regen-Weiterführung" in text
        assert "Status: reaktiviert" in text
        assert "vorherige Zell-ID beibehalten" in text
