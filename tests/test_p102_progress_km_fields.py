"""P102: Lernfortschrittsseite (Progress.jsx) muss die seit B492/B493 verfuegbaren
km-Felder anzeigen und Alt-Versionen (legacy_incomparable) aus Differenzdiagrammen
ausschliessen, statt Pixel- und km-Werte unbemerkt zu mischen."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PAGE = REPO_ROOT / "frontend" / "src" / "pages" / "Progress.jsx"
APP = REPO_ROOT / "app.py"


def _page():
    return PAGE.read_text(encoding="utf-8")


def _app():
    return APP.read_text(encoding="utf-8")


def test_backend_forwards_km_fields():
    src = _app()
    for field in ("mae_km_old", "mae_km_new", "mae_by_horizon_old_km",
                  "mae_by_horizon_new_km", "paired_samples_by_horizon", "legacy_incomparable"):
        assert f'"{field}"' in src, f"{field} wird nicht durch _progress_normalize_meta gereicht"


def test_frontend_uses_km_fields_not_only_legacy_px():
    t = _page()
    assert "mae_km_new" in t
    assert "mae_by_horizon_new_km" in t
    assert "kinematische Baseline" in t


def test_legacy_versions_are_excluded_from_comparison_charts():
    t = _page()
    assert "comparableVersions" in t
    assert "isLegacy" in t
    assert "legacy_incomparable" in t


def test_paired_samples_are_surfaced():
    t = _page()
    assert "paired_samples_by_horizon" in t


def test_new_rejection_reason_is_explained():
    assert "rejected_low_samples_per_horizon" in _page()
