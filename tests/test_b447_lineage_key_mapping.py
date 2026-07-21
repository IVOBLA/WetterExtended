"""B447/B449: contributing_lineage_ids wird aus den echten Zell-Schlüsseln befüllt.

KI-Report 2026-07-21 (AC-020): Die Identitätsextraktion las 'lineage_id'/'parent_cell_ids',
die kein Zellobjekt besitzt (object_tracking.py schreibt 'cell_id'/'id', 'parents',
'lineage'). Ergebnis: contributing_lineage_ids strukturell immer leer (628/628 Samples).

B449: Die Extraktion ist als _cell_identity() ausgelagert und hier direkt getestet — der
frühere Test lief nie bis in den shapely-abhängigen Overlap-Pfad und prüfte faktisch
nichts.
"""
import hydro_flood_ml


def test_cell_id_wird_zu_lineage_id():
    cell = {"cell_id": "WX-20260720-0601", "id": "GH3CNRA2",
            "lineage": "continued", "parents": ["GH3CNRA2"]}
    identity = hydro_flood_ml._cell_identity(cell)
    assert identity.get("lineage_id") == "WX-20260720-0601"
    assert identity.get("parent_cell_ids") == ["GH3CNRA2"]


def test_kein_lineage_id_schluessel_noetig():
    """Explizit: Input hat KEINE 'lineage_id'/'parent_cell_ids'-Schlüssel."""
    cell = {"cell_id": "WX-1", "id": "AAA", "parents": ["AAA"]}
    assert "lineage_id" not in cell and "parent_cell_ids" not in cell
    identity = hydro_flood_ml._cell_identity(cell)
    assert identity["lineage_id"] == "WX-1"


def test_fallback_auf_id_wenn_cell_id_fehlt():
    cell = {"id": "GH3CNRA2", "parents": []}
    identity = hydro_flood_ml._cell_identity(cell)
    assert identity.get("lineage_id") == "GH3CNRA2"


def test_leere_parents_werden_weggelassen():
    cell = {"cell_id": "WX-2", "parents": []}
    identity = hydro_flood_ml._cell_identity(cell)
    assert "parent_cell_ids" not in identity  # leere Liste → kein Schlüssel


def test_origin_type_und_tracking_state_durchgereicht():
    cell = {"cell_id": "WX-3", "origin_type": "convective", "tracking_state": "mature"}
    identity = hydro_flood_ml._cell_identity(cell)
    assert identity["origin_type"] == "convective"
    assert identity["tracking_state"] == "mature"


def test_zelle_ohne_identitaet_liefert_leeres_dict():
    assert hydro_flood_ml._cell_identity({}) == {}


def test_produktivpfad_nutzt_cell_identity():
    """Strukturnachweis: _precip_from_cells verwendet die extrahierte Funktion."""
    import inspect
    src = inspect.getsource(hydro_flood_ml._precip_from_cells)
    assert "_cell_identity(cell)" in src, \
        "Produktivpfad ruft _cell_identity nicht auf — Fix und Test driften auseinander."


def test_lineage_liste_aus_identity_ableitbar():
    """End-to-end der Ableitung: aus mehreren Zellen ergibt sich eine nicht-leere,
    deduplizierte Lineage-Liste (die Logik von build_feature_row nachgebildet auf
    _cell_identity, ohne den Geometrie-Pfad)."""
    cells = [
        {"cell_id": "WX-A", "parents": ["P1"]},
        {"cell_id": "WX-B", "parents": ["P2"]},
        {"cell_id": "WX-A", "parents": ["P1"]},  # Duplikat
    ]
    lineage_ids = sorted({
        str(_id["lineage_id"])
        for _id in (hydro_flood_ml._cell_identity(c) for c in cells)
        if _id.get("lineage_id") not in (None, "")
    })
    assert lineage_ids == ["WX-A", "WX-B"]
