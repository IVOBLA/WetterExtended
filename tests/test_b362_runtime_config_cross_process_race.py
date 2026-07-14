"""B362: runtime_config.patch()/patch_exact_key() muessen unmittelbar vor dem
Merge frisch von der Platte laden, sonst ueberschreibt ein Prozess mit
veraltetem In-Memory-Cache zwischenzeitliche Schreibvorgaenge eines ANDEREN
Prozesses lautlos (siehe LOCATIONS_WATCHLIST-Datenverlust-Analyse)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_patch_reloads_before_merge():
    src = _read("runtime_config.py")
    fn = src.split("def patch(partial: dict) -> dict:")[1].split("\ndef ")[0]
    assert "reload_overrides()" in fn.split("with _LOCK:")[0], \
        "patch() laedt nicht mehr frisch von der Platte VOR dem Merge"


def test_patch_exact_key_reloads_before_merge():
    src = _read("runtime_config.py")
    fn = src.split("def patch_exact_key(top_key: str, value) -> dict:")[1].split("\ndef ")[0]
    assert "reload_overrides()" in fn, \
        "patch_exact_key() laedt nicht mehr frisch von der Platte VOR dem Merge"


def test_patch_does_not_clobber_concurrent_external_write(tmp_path, monkeypatch):
    """Simuliert das beobachtete Szenario: ein anderer 'Prozess' schreibt
    LOCATIONS_WATCHLIST direkt auf die Platte (ohne den In-Memory-Cache
    dieses Testprozesses zu beruehren). Ein anschliessender patch() fuer
    einen VOELLIG ANDEREN Key darf LOCATIONS_WATCHLIST NICHT verlieren."""
    import config
    import runtime_config as rc

    override_path = tmp_path / "runtime_overrides.json"
    monkeypatch.setattr(config, "RUNTIME_OVERRIDES_PATH", str(override_path), raising=False)

    # Ausgangszustand: dieser Prozess hat einen VERALTETEN Cache (leer/alt),
    # der NICHTS von LOCATIONS_WATCHLIST weiss.
    rc.reload_overrides()
    assert "LOCATIONS_WATCHLIST" not in rc._OVERRIDES

    # "Anderer Prozess" schreibt LOCATIONS_WATCHLIST direkt auf die Platte,
    # OHNE den In-Memory-Cache dieses Testprozesses zu aktualisieren.
    external_locations = [{"name": "Klagenfurt", "lat": 46.6228, "lon": 14.305,
                            "radius_km": 5.0, "email": "test@example.com"}]
    override_path.write_text(
        json.dumps({"LOCATIONS_WATCHLIST": external_locations}), encoding="utf-8"
    )

    # Dieser Prozess patcht jetzt einen VOELLIG ANDEREN Key, OHNE selbst
    # zuvor manuell reload_overrides() aufgerufen zu haben.
    result = rc.patch({"ML_ALLOW_LEGACY_SAMPLES": True})

    assert result.get("LOCATIONS_WATCHLIST") == external_locations, \
        "LOCATIONS_WATCHLIST wurde durch patch() eines anderen Keys ueberschrieben (Race)"
    assert result.get("ML_ALLOW_LEGACY_SAMPLES") is True

    on_disk = json.loads(override_path.read_text(encoding="utf-8"))
    assert on_disk.get("LOCATIONS_WATCHLIST") == external_locations
