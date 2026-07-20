"""B434: Angemeldete hydro_static-Dateien dürfen nicht verworfen werden."""
import json
from pathlib import Path

import pytest

import debug_export


def test_jede_angemeldete_datei_steht_in_der_allowlist():
    fehlend = [
        path.name
        for path in debug_export.HYDRO_STATIC_EXPORT_FILES
        if path.name not in debug_export._HYDRO_STATIC_EXPORT_ALLOWLIST
    ]
    assert fehlend == [], (
        f"In roots angemeldet, aber von _is_excluded verworfen: {fehlend}. "
        "_is_excluded greift vor der force-Auswertung."
    )


def test_station_catchments_ist_angemeldet_und_erlaubt():
    expected = Path("train_data/hydro/static/generated/station_catchments.geojson")
    assert expected in debug_export.HYDRO_STATIC_EXPORT_FILES
    assert expected.name in debug_export._HYDRO_STATIC_EXPORT_ALLOWLIST


def _make_static_tree(base: Path) -> None:
    generated = base / "train_data" / "hydro" / "static" / "generated"
    generated.mkdir(parents=True)
    (generated / "station_catchments.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8"
    )
    (generated / "station_network_index.json").write_text("{}", encoding="utf-8")
    (generated / "hydro_static_status.json").write_text("{}", encoding="utf-8")
    source = base / "train_data" / "hydro" / "static" / "source"
    source.mkdir(parents=True)
    (source / "basins.geojson").write_text("{}", encoding="utf-8")


@pytest.mark.parametrize(
    "name, expected",
    [
        ("station_catchments.geojson", False),
        ("station_network_index.json", False),
        ("hydro_static_status.json", False),
        ("hydro_upstream_diagnostics.json", False),
        ("hydro_static_coverage.json", False),
        ("irgendwas_grosses.gdb", True),
    ],
)
def test_is_excluded_entscheidet_nach_allowlist(tmp_path, name, expected):
    generated = tmp_path / "train_data" / "hydro" / "static" / "generated"
    generated.mkdir(parents=True)
    path = generated / name
    path.write_text("{}", encoding="utf-8")
    assert debug_export._is_excluded(path, tmp_path) is expected


def test_quelldateien_bleiben_ausgeschlossen(tmp_path):
    _make_static_tree(tmp_path)
    source = tmp_path / "train_data" / "hydro" / "static" / "source" / "basins.geojson"
    assert debug_export._is_excluded(source, tmp_path) is True


def test_kandidaten_enthalten_die_einzugsgebiete(tmp_path):
    _make_static_tree(tmp_path)
    candidates, diagnostics = debug_export._build_candidates_with_diagnostics(tmp_path, {})
    assert "station_catchments.geojson" in {candidate.arc_rel.name for candidate in candidates}
    assert diagnostics["dropped_expected_files"] == []


def test_diagnostik_meldet_eine_verworfene_angemeldete_datei(tmp_path, monkeypatch):
    _make_static_tree(tmp_path)
    reduced = set(debug_export._HYDRO_STATIC_EXPORT_ALLOWLIST) - {"station_catchments.geojson"}
    monkeypatch.setattr(debug_export, "_HYDRO_STATIC_EXPORT_ALLOWLIST", reduced)
    _candidates, diagnostics = debug_export._build_candidates_with_diagnostics(tmp_path, {})
    assert diagnostics["dropped_expected_files"] == [
        "train_data/hydro/static/generated/station_catchments.geojson"
    ]


def test_fehlende_datei_erzeugt_keine_falschmeldung(tmp_path):
    generated = tmp_path / "train_data" / "hydro" / "static" / "generated"
    generated.mkdir(parents=True)
    (generated / "hydro_static_status.json").write_text("{}", encoding="utf-8")
    _candidates, diagnostics = debug_export._build_candidates_with_diagnostics(tmp_path, {})
    assert diagnostics["dropped_expected_files"] == []
