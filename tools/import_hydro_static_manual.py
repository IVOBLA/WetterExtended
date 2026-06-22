#!/usr/bin/env python3
"""Produktiver manueller Hydro-Static-Import für Kärnten/Feldkirchen.

Das Script ist absichtlich konservativ: neue GeoJSON-Dateien werden zuerst in
Temporärdateien geschrieben, validiert und nur danach atomar ersetzt. Kleine
leere OGR-FeatureCollections (z. B. 161/163 Bytes) gelten immer als ungültig.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import hydro_static_import as hsi  # noqa: E402

LIVE_URL = "https://info.ktn.gv.at/asp/hydro/daten/json/hdkaernten_abfluss_lite.json"
BASINS_URL = "https://inspire.lfrz.gv.at/000801/ds/AT_DRAINAGEBASIN_GDB.zip"
FLOWLINES_URL = "https://inspire.lfrz.gv.at/000801/ds/AT_WATERCOURSELINK_GDB.zip"
WATERCOURSE_FALLBACK_URL = "https://inspire.lfrz.gv.at/000801/ds/AT_WATERCOURSE_GML.zip"
KAERNTEN_BBOX = [12.6, 46.36, 15.2, 47.18]
FELDKIRCHEN_BBOX = hsi.FELDKIRCHEN_BBOX
MIN_GEOJSON_BYTES = {"stations": 120, "basins": 200, "flowlines": 200}
REQUIRED_TOOLS = ["curl", "unzip", "ogrinfo", "ogr2ogr", "python3"]


@dataclass
class RunContext:
    args: argparse.Namespace
    static_dir: Path = Path("train_data/hydro/static")
    live_dir: Path = Path("train_data/hydro/live")
    downloads: dict[str, dict[str, Any]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def source_dir(self) -> Path: return self.static_dir / "source"
    @property
    def download_dir(self) -> Path: return self.source_dir / "_downloads"
    @property
    def generated_dir(self) -> Path: return self.static_dir / "generated"
    @property
    def backup_dir(self) -> Path: return self.static_dir / "backup"
    @property
    def stations_geojson(self) -> Path: return self.source_dir / "hydro_stations.geojson"
    @property
    def basins_geojson(self) -> Path: return self.source_dir / "basins.geojson"
    @property
    def flowlines_geojson(self) -> Path: return self.source_dir / "flowlines.geojson"
    @property
    def live_json(self) -> Path: return self.live_dir / "latest_hydro.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dirs(ctx: RunContext) -> None:
    for p in (ctx.live_dir, ctx.source_dir, ctx.download_dir, ctx.generated_dir, ctx.backup_dir):
        if not ctx.args.dry_run:
            p.mkdir(parents=True, exist_ok=True)


def check_tools() -> list[str]:
    return [tool for tool in REQUIRED_TOOLS if shutil.which(tool) is None]


def run_cmd(cmd: list[str], *, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=False, timeout=timeout)


def valid_zip(path: Path) -> bool:
    if not path.exists() or path.stat().st_size <= 0 or not zipfile.is_zipfile(path):
        return False
    res = run_cmd(["unzip", "-t", str(path)], timeout=120)
    return res.returncode == 0


def download_if_needed(ctx: RunContext, url: str, name: str, *, force: bool = False) -> Path:
    target = ctx.download_dir / (Path(urlparse(url).path).name or f"{name}.zip")
    cached = valid_zip(target)
    info = {"url": url, "path": str(target), "status": "cached" if cached else "missing", "size_bytes": target.stat().st_size if target.exists() else 0}
    if cached and not force:
        ctx.downloads[name] = info
        return target
    if ctx.args.no_network:
        raise RuntimeError(f"--no-network: kein gültiger lokaler Cache für {name}: {target}")
    if ctx.args.dry_run:
        info["status"] = "dry_run_download_skipped"; ctx.downloads[name] = info; return target
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with urlopen(url, timeout=90) as r:  # nosec: offizielle freie Datenquelle, URL konstant
        tmp.write_bytes(r.read())
    if not valid_zip(tmp):
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Download ungültig oder ZIP-Test fehlgeschlagen: {url}")
    os.replace(tmp, target)
    info.update(status="downloaded", size_bytes=target.stat().st_size)
    ctx.downloads[name] = info
    return target


def parse_ogr_layers(text: str) -> list[str]:
    layers: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        low = line.lower()
        if low.startswith("layer:") or low.startswith("layer name:"):
            name = line.split(":", 1)[1].split("(", 1)[0].strip()
        elif line[:1].isdigit() and ":" in line:
            name = line.split(":", 1)[1].split("(", 1)[0].strip()
        else:
            continue
        if name:
            layers.append(name)
    return layers


def layer_geometry(dataset: str, layer: str) -> str:
    out = run_cmd(["ogrinfo", "-so", dataset, layer], timeout=120).stdout
    for line in out.splitlines():
        low = line.lower()
        if "geometry:" in low or "geometry type:" in low:
            return line.split(":", 1)[1].strip()
        if "multi polygon" in low or "multipolygon" in low: return "MultiPolygon"
        if "line string" in low or "linestring" in low: return "LineString"
        if "polygon" in low: return "Polygon"
    return ""


def is_layer_geometry_allowed(geometry: str, kind: str) -> bool:
    g = geometry.lower().replace(" ", "")
    if not g:
        return False
    if kind == "basins":
        return "polygon" in g
    return "linestring" in g


def ogr_layers(dataset: str) -> list[str]:
    return parse_ogr_layers(run_cmd(["ogrinfo", dataset], timeout=120).stdout)


def bbox_feature_count(dataset: str, layer: str, bbox: list[float]) -> int:
    cmd = ["ogrinfo", "-so", "-spat_srs", "EPSG:4326", "-spat", *map(str, bbox), dataset, layer]
    out = run_cmd(cmd, timeout=120).stdout
    for line in out.splitlines():
        if "feature count:" in line.lower():
            try: return int(line.split(":", 1)[1].strip())
            except ValueError: return -1
    return -1


def select_layer(dataset: str, kind: str, bbox: list[float] = KAERNTEN_BBOX) -> str:
    candidates = []
    for layer in ogr_layers(dataset):
        geom = layer_geometry(dataset, layer)
        if is_layer_geometry_allowed(geom, kind):
            candidates.append((bbox_feature_count(dataset, layer, bbox), layer))
    if not candidates:
        raise RuntimeError(f"Keine gültigen {'Polygon' if kind == 'basins' else 'LineString'}-Layer gefunden: {dataset}")
    if kind == "flowlines":
        candidates.sort(key=lambda x: x[0], reverse=True)
        if candidates[0][0] <= 0:
            raise RuntimeError(f"Keine Flowline-Treffer in Kärnten-BBOX: {dataset}")
        return candidates[0][1]
    candidates.sort(key=lambda x: (0 if x[0] > 0 else 1, -x[0]))
    return candidates[0][1]


def extract_zip(path: Path) -> str:
    out = path.with_suffix("")
    if not out.exists() or not any(out.iterdir()):
        out.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path) as zf:
            zf.extractall(out)
    for pattern in ("*.gdb", "*.gpkg", "*.gml", "*.xml", "*.shp"):
        found = list(out.rglob(pattern))
        if found:
            return str(found[0])
    return str(out)


def ogr2ogr_command(tmp: Path, dataset: str, layer: str, bbox: list[float]) -> list[str]:
    return ["ogr2ogr", "-f", "GeoJSON", "-t_srs", "EPSG:4326", "-spat_srs", "EPSG:4326", "-spat", *map(str, bbox), str(tmp), dataset, layer]


def validate_geojson(path: Path, kind: str, bbox: list[float] = KAERNTEN_BBOX) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"{path} fehlt")
    if path.stat().st_size <= MIN_GEOJSON_BYTES[kind] or path.stat().st_size in (161, 163):
        raise ValueError(f"{path.name} ist zu klein/leer ({path.stat().st_size} Bytes)")
    if kind == "stations":
        data = json.loads(path.read_text(encoding="utf-8"))
        feats = data.get("features") if isinstance(data, dict) else None
        if not feats: raise ValueError(f"{path.name} enthält keine Features")
        hits = [f for f in feats if (f.get("geometry") or {}).get("type") == "Point" and hsi._bbox_intersects(hsi._geom_bbox(f.get("geometry")), bbox)]
        if not hits: raise ValueError(f"{path.name} enthält keine Point-Features in Kärnten-BBOX")
        return {"feature_count": len(feats), "bbox_hit_count": len(hits)}
    return hsi.validate_geojson_output(str(path), kind, bbox)


def normalize_basins(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    fields = ["HYDROID", "ID", "IDENTIFIER", "INSPIREID_IDENTIFIER_LOCALID", "OBJECTID", "localId", "gml_id"]
    for idx, f in enumerate(data.get("features") or [], 1):
        props = f.setdefault("properties", {})
        low = {str(k).lower(): v for k, v in props.items()}
        ident = next((props.get(k) for k in fields if props.get(k) not in (None, "")), None)
        if ident is None:
            ident = next((low.get(k.lower()) for k in fields if low.get(k.lower()) not in (None, "")), idx)
        for key in ("catchment_id", "basin_id", "id"):
            props[key] = str(ident)
        props["hydro_id_original"] = str(ident)
        props["source_schema"] = "GGN_DRAINAGEBASIN"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def normalize_flowlines(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    for idx, f in enumerate(data.get("features") or [], 1):
        props = f.setdefault("properties", {})
        low = {str(k).lower(): v for k, v in props.items()}
        ident = props.get("watercourse_id") or props.get("hydro_id") or low.get("id") or low.get("objectid") or low.get("gml_id") or str(idx)
        name = props.get("name") or props.get("river_name") or low.get("name") or low.get("gewaesser") or low.get("gn") or ""
        props.setdefault("watercourse_id", str(ident)); props.setdefault("hydro_id", str(ident))
        props.setdefault("name", str(name)); props.setdefault("river_name", str(name))
        props["source_schema"] = props.get("source_schema") or "INSPIRE_WATERCOURSE"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def convert_dataset_atomically(ctx: RunContext, zip_path: Path, dst: Path, kind: str) -> None:
    dataset = extract_zip(zip_path)
    layer = select_layer(dataset, kind, KAERNTEN_BBOX)
    if ctx.args.dry_run:
        print(f"DRY-RUN ogr2ogr: {' '.join(ogr2ogr_command(dst.with_suffix(dst.suffix+'.tmp'), dataset, layer, KAERNTEN_BBOX))}")
        return
    fd, tmp_name = tempfile.mkstemp(prefix=f".{dst.name}.", suffix=".tmp", dir=str(dst.parent)); os.close(fd)
    tmp = Path(tmp_name)
    try:
        res = run_cmd(ogr2ogr_command(tmp, dataset, layer, KAERNTEN_BBOX), timeout=600)
        if res.returncode != 0:
            raise RuntimeError((res.stderr or res.stdout or "ogr2ogr fehlgeschlagen").strip())
        if kind == "basins": normalize_basins(tmp)
        if kind == "flowlines": normalize_flowlines(tmp)
        validate_geojson(tmp, kind, KAERNTEN_BBOX)
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)


def import_stations(ctx: RunContext) -> None:
    if validate_existing(ctx.stations_geojson, "stations") and not ctx.args.force_live:
        return
    if ctx.args.no_network and not ctx.live_json.exists():
        raise RuntimeError("--no-network: latest_hydro.json fehlt")
    if not ctx.args.dry_run and (ctx.args.force_live or not ctx.live_json.exists()):
        if ctx.args.no_network: raise RuntimeError("--no-network: Live-Download nicht erlaubt")
        with urlopen(LIVE_URL, timeout=30) as r:  # nosec: offizielle freie Datenquelle, URL konstant
            ctx.live_json.write_bytes(r.read())
    if ctx.args.dry_run: return
    gj = hsi.hydro_json_to_geojson(json.loads(ctx.live_json.read_text(encoding="utf-8")))
    tmp = ctx.stations_geojson.with_suffix(".geojson.tmp")
    tmp.write_text(json.dumps(gj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    validate_geojson(tmp, "stations", KAERNTEN_BBOX)
    os.replace(tmp, ctx.stations_geojson)


def validate_existing(path: Path, kind: str) -> bool:
    try:
        validate_geojson(path, kind, KAERNTEN_BBOX)
        return True
    except Exception:
        return False


def import_basins(ctx: RunContext) -> None:
    if validate_existing(ctx.basins_geojson, "basins") and not ctx.args.force:
        return
    z = download_if_needed(ctx, BASINS_URL, "basins", force=ctx.args.force)
    convert_dataset_atomically(ctx, z, ctx.basins_geojson, "basins")


def import_flowlines(ctx: RunContext) -> None:
    if validate_existing(ctx.flowlines_geojson, "flowlines") and not ctx.args.force:
        return
    errors = []
    for name, url in (("flowlines", FLOWLINES_URL), ("watercourse", WATERCOURSE_FALLBACK_URL)):
        try:
            z = download_if_needed(ctx, url, name, force=ctx.args.force)
            convert_dataset_atomically(ctx, z, ctx.flowlines_geojson, "flowlines")
            return
        except Exception as exc:
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
    raise RuntimeError("Offizielle Flowline-Quellen nicht importierbar: " + "; ".join(errors))


def build_index(ctx: RunContext) -> dict[str, Any]:
    if ctx.args.dry_run:
        return {}
    return hsi.build_static_hydro(str(ctx.static_dir), downloads=ctx.downloads)


def write_coverage(ctx: RunContext, area: str = "feldkirchen") -> dict[str, Any]:
    if ctx.args.dry_run:
        return {"coverage_ok": False, "area": area, "errors": ["dry_run"], "generated_at": now()}
    return hsi.check_coverage(area, str(ctx.static_dir))


def write_manual_status(ctx: RunContext, coverage: dict[str, Any] | None, status: dict[str, Any] | None = None) -> dict[str, Any]:
    paths = hsi.static_paths(str(ctx.static_dir)) if ctx.args.dry_run else hsi.ensure_static_dirs(str(ctx.static_dir))
    station_count = hsi._count_geojson(paths["stations_source"])
    basin_count = hsi._count_geojson(paths["basins_source"])
    flow_count = hsi._count_geojson(paths["flowlines_source"])
    base = dict(status or {})
    station_basin = int(base.get("station_basin_count") or base.get("station_basin_match_count") or base.get("station_basin_match_count", 0) or 0)
    basins_ok = validate_existing(ctx.basins_geojson, "basins")
    flows_ok = validate_existing(ctx.flowlines_geojson, "flowlines")
    if not station_count or not basins_ok:
        code = "hydro_static_missing"
    elif not flows_ok:
        code = "flowlines_missing"
    elif station_basin > 0:
        code = "upstream_topology_missing" if base.get("topology_source") in (None, "none", "basin_only") else str(base.get("status", "station_basin_available"))
    else:
        code = "basins_available"
    payload = {
        **base, "ok": code == "hydro_static_ready", "status": code,
        "message": base.get("message") or code,
        "station_count": station_count, "static_station_count": station_count,
        "station_basin_count": station_basin, "basin_count": basin_count, "flowline_count": flow_count,
        "flowlines_available": flows_ok, "basins_available": basins_ok,
        "feldkirchen_coverage_ok": bool(coverage and coverage.get("coverage_ok")),
        "impact_eligible_station_count": int(base.get("impact_eligible_station_count") or 0) if base.get("topology_source") not in (None, "none", "basin_only") else 0,
        "topology_source": base.get("topology_source") or "none", "downloads": ctx.downloads,
        "missing": base.get("missing", []), "errors": ctx.errors + base.get("errors", []),
        "warnings": ctx.warnings + base.get("warnings", []), "generated_at": now(),
    }
    if not ctx.args.dry_run:
        (ctx.generated_dir / "hydro_static_status.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


def print_summary(status: dict[str, Any], coverage: dict[str, Any] | None) -> None:
    cov = coverage or {}
    print("\nHydro-Static Manual Import")
    print(f"Stations: {status.get('station_count', 0)} {'OK' if status.get('station_count', 0) else 'FAIL'}")
    print(f"Basins: {status.get('basin_count', 0)} {'OK' if status.get('basin_count', 0) else 'FAIL'}")
    print(f"Flowlines: {status.get('flowline_count', 0)} {'OK' if status.get('flowline_count', 0) else 'FAIL'}")
    print(f"Feldkirchen Basins: {cov.get('basin_features_feldkirchen', 0)} {'OK' if cov.get('basin_features_feldkirchen', 0) else 'FAIL'}")
    print(f"Feldkirchen Flowlines: {cov.get('flowline_features_feldkirchen', 0)} {'OK' if cov.get('flowline_features_feldkirchen', 0) else 'FAIL'}")
    print(f"Station-Basin Matches: {status.get('station_basin_count', 0)} {'OK' if status.get('station_basin_count', 0) else 'WARN'}")
    ies = status.get('impact_eligible_station_count', 0)
    print(f"Impact Eligible Stations: {ies} {'OK' if ies else 'WARN upstream_topology_missing'}")
    print(f"Status: {status.get('status')}")
    if status.get("errors"):
        print("Fehler:"); [print(f"- {e}") for e in status["errors"]]
        print("Manuelle Pakete: sudo apt install -y gdal-bin unzip curl jq")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Manueller Hydro-Static-Import Kärnten/Feldkirchen")
    p.add_argument("--all", action="store_true"); p.add_argument("--force", action="store_true"); p.add_argument("--force-live", action="store_true")
    p.add_argument("--stations-only", action="store_true"); p.add_argument("--basins-only", action="store_true"); p.add_argument("--flowlines-only", action="store_true")
    p.add_argument("--check-coverage", choices=["feldkirchen"]); p.add_argument("--validate-only", action="store_true")
    p.add_argument("--dry-run", action="store_true"); p.add_argument("--no-network", action="store_true"); p.add_argument("--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv); ctx = RunContext(args)
    ensure_dirs(ctx)
    missing_tools = check_tools()
    if missing_tools:
        print(f"Fehlende Tools: {', '.join(missing_tools)}", file=sys.stderr)
        print("sudo apt install -y gdal-bin unzip curl jq", file=sys.stderr)
        return 2
    do_all = args.all or not any((args.stations_only, args.basins_only, args.flowlines_only, args.validate_only))
    try:
        if not args.validate_only:
            if do_all or args.stations_only: import_stations(ctx)
            if do_all or args.basins_only: import_basins(ctx)
            if do_all or args.flowlines_only: import_flowlines(ctx)
        for path, kind in ((ctx.stations_geojson, "stations"), (ctx.basins_geojson, "basins"), (ctx.flowlines_geojson, "flowlines")):
            if path.exists(): validate_geojson(path, kind, KAERNTEN_BBOX)
        status0 = build_index(ctx) if not args.validate_only else hsi.status(str(ctx.static_dir))
        coverage = write_coverage(ctx, args.check_coverage or "feldkirchen")
        status = write_manual_status(ctx, coverage, status0)
    except Exception as exc:
        ctx.errors.append(f"{type(exc).__name__}: {exc}")
        coverage = write_coverage(ctx, args.check_coverage or "feldkirchen") if not args.dry_run else {"coverage_ok": False, "errors": ctx.errors}
        status = write_manual_status(ctx, coverage, {})
        print_summary(status, coverage)
        return 1
    print_summary(status, coverage)
    return 0 if not status.get("errors") else 1


if __name__ == "__main__":
    raise SystemExit(main())
