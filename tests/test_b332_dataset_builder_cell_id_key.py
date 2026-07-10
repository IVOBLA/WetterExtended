"""B332: Sequenzbildung in dataset_builder.py schluesselt auf cell_id
(Fallback id), damit Merge/Split/IR-Precursor-stabilisierte Identitaeten
nicht durch einen id-Wechsel eine Sequenz verlieren."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest


def _write_frame(tmp_path, ts, objs, weather=None):
    obj_dir = tmp_path / "objects"
    wthr_dir = tmp_path / "weather"
    obj_dir.mkdir(exist_ok=True)
    wthr_dir.mkdir(exist_ok=True)
    name = ts.strftime("%Y-%m-%d_%H-%M-%S") + ".json"
    (obj_dir / name).write_text(json.dumps(objs), encoding="utf-8")
    (wthr_dir / name).write_text(json.dumps(weather or []), encoding="utf-8")


class _FakeArray(list):
    @property
    def shape(self):
        if not self:
            return (0,)
        if isinstance(self[0], list):
            if self[0] and isinstance(self[0][0], list):
                return (len(self), len(self[0]), len(self[0][0]))
            return (len(self), len(self[0]))
        return (len(self),)

    def reshape(self, *shape):
        if shape == (-1, 2):
            return [self[i:i + 2] for i in range(0, len(self), 2)]
        return self


def _fake_asarray(values, dtype=None):
    if isinstance(values, _FakeArray):
        return values
    return _FakeArray(values)


def _patch_dataset_builder(monkeypatch, ds, tmp_path):
    monkeypatch.setattr(ds, "SAVE_PATHS", {
        "objects": str(tmp_path / "objects"),
        "weather": str(tmp_path / "weather"),
        "dataset": str(tmp_path / "dataset"),
    }, raising=False)
    monkeypatch.setattr(ds, "np", SimpleNamespace(
        array=_fake_asarray,
        asarray=_fake_asarray,
        savez=lambda *a, **k: None,
    ), raising=False)
    monkeypatch.setattr(ds, "pd", SimpleNamespace(
        DataFrame=lambda rows: SimpleNamespace(
            to_parquet=lambda *a, **k: None,
        ),
    ), raising=False)
    monkeypatch.setattr(ds, "joblib", SimpleNamespace(dump=lambda *a, **k: None), raising=False)
    monkeypatch.setattr(
        ds, "_fit_nan_aware_standard_scaler", lambda values: (None, values), raising=False
    )
    monkeypatch.setattr(ds, "ML_SEQUENCE_LENGTH", 2, raising=False)
    monkeypatch.setattr(ds, "_dependencies_available", lambda: [], raising=False)
    monkeypatch.setattr(ds, "_schema_policy_allows_legacy", lambda: True, raising=False)
    monkeypatch.setattr(
        ds, "compare_sample_schema", lambda *a, **k: (True, None), raising=False
    )
    monkeypatch.setattr(ds, "validate_sample", lambda *a, **k: (True, None), raising=False)


def test_sequenz_entsteht_trotz_id_wechsel_bei_stabiler_cell_id(monkeypatch, tmp_path):
    """Kernfall: dieselbe cell_id, aber eine andere 'id' in einem der Frames
    (z.B. nach einem kurzen Tracking-Sprung) darf die Sequenz nicht mehr
    verhindern -- vor B332 waere common_ids in diesem Fall leer gewesen."""
    ds = pytest.importorskip("dataset_builder")
    _patch_dataset_builder(monkeypatch, ds, tmp_path)

    t0 = datetime(2026, 7, 9, 17, 15, 0)
    t1 = t0 + timedelta(minutes=5)
    t2 = t1 + timedelta(minutes=10)

    base_obj = {"cell_id": "WX-20260709-0006", "x": 100.0, "y": 200.0,
                "lat": 46.6, "lon": 14.3}
    _write_frame(tmp_path, t0, [dict(base_obj, id="OLD_ID_1")])
    _write_frame(tmp_path, t1, [dict(base_obj, id="NEW_ID_2", x=101.0, y=201.0)])
    _write_frame(tmp_path, t2, [dict(base_obj, id="NEW_ID_2", x=102.0, y=202.0)])

    result = ds.build_dataset()

    assert len(result.get("ids", [])) > 0, (
        "Trotz id-Wechsel zwischen den Frames muss ueber die stabile cell_id "
        "mindestens eine Sequenz entstehen."
    )


def test_legacy_frame_ohne_cell_id_faellt_auf_id_zurueck(monkeypatch, tmp_path):
    """Rueckwaertskompatibilitaet: Frames ganz ohne cell_id-Feld (aeltere
    Datenbestaende) muessen weiterhin ueber 'id' gematcht werden."""
    ds = pytest.importorskip("dataset_builder")
    _patch_dataset_builder(monkeypatch, ds, tmp_path)

    t0 = datetime(2026, 7, 9, 17, 15, 0)
    t1 = t0 + timedelta(minutes=5)
    t2 = t1 + timedelta(minutes=10)

    legacy_obj = {"id": "LEGACY_ID_1", "x": 50.0, "y": 60.0, "lat": 46.6, "lon": 14.3}
    _write_frame(tmp_path, t0, [dict(legacy_obj)])
    _write_frame(tmp_path, t1, [dict(legacy_obj, x=51.0, y=61.0)])
    _write_frame(tmp_path, t2, [dict(legacy_obj, x=52.0, y=62.0)])

    result = ds.build_dataset()

    assert len(result.get("ids", [])) > 0, (
        "Legacy-Frames ohne cell_id muessen weiterhin ueber 'id' zu einer "
        "Sequenz zusammengefuehrt werden (Fallback)."
    )
