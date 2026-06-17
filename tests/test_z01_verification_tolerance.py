"""Z01: Verifikations-Zieltoleranz ist an die Zieldefinition (<1 km) angeglichen."""
import config


def test_tolerance_aligned_to_target():
    assert float(config.VERIFICATION_TOLERANCE_KM) == 1.0


def test_tolerance_no_longer_5km():
    assert float(config.VERIFICATION_TOLERANCE_KM) < 5.0


def test_search_radius_unchanged():
    # Der Nearest-Neighbor-Suchradius bleibt großzügig (nur die Treffer-Toleranz ist streng).
    assert float(config.VERIFICATION_MAX_SEARCH_RADIUS_KM) == 25.0
