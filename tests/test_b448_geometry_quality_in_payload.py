"""B448: geometry_quality wird in die Sample-Payload durchgereicht (für AC-032).

KI-Report 2026-07-21: geometry_quality fehlte in labeled_samples (3376× None), AC-032
(bbox_fallback-Toter-Code-Prüfung) war dadurch nicht über den Export bewertbar.
geometry_quality ist ein Diagnose-Feld, kein ML-Feature — daher auf Payload-Top-Level,
ohne FEATURE_SCHEMA_VERSION zu berühren.
"""
import re
from pathlib import Path

SRC = Path("hydro_flood_ml.py").read_text(encoding="utf-8")


def test_geometry_quality_in_payload():
    assert '"geometry_quality": row.get("geometry_quality")' in SRC, \
        "geometry_quality wird nicht in die Payload übernommen."


def test_geometry_quality_vor_features_ausserhalb_feature_vektor():
    """Muss außerhalb des 'features'-Vektors stehen, sonst Schema-Bruch."""
    # In derselben Payload-Zeile: geometry_quality steht direkt vor "features".
    m = re.search(r'"geometry_quality": row\.get\("geometry_quality"\), "features":', SRC)
    assert m, "geometry_quality steht nicht unmittelbar vor dem features-Vektor."


def test_geometry_quality_kein_feature_key():
    """Gegenprobe: geometry_quality darf in keiner Feature-Spaltenliste stehen."""
    for m in re.finditer(r'FEATURE_(?:COLUMNS|KEYS|ORDER)\s*=\s*[\[(](.*?)[\])]', SRC, re.S):
        assert "geometry_quality" not in m.group(1), \
            "geometry_quality ist fälschlich Teil des Feature-Vektors."


def test_feature_schema_version_unveraendert():
    """B448 darf FEATURE_SCHEMA_VERSION nicht anfassen."""
    m = re.search(r'FEATURE_SCHEMA_VERSION\s*=\s*["\']([^"\']+)["\']', SRC)
    assert m, "FEATURE_SCHEMA_VERSION nicht gefunden."
    # Der Wert darf nicht auf ein B448-spezifisches Schema zeigen.
    assert "b448" not in m.group(1).lower(), \
        "FEATURE_SCHEMA_VERSION wurde für B448 geändert — nicht vorgesehen."
