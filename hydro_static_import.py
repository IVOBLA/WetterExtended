"""Import-Werkzeuge für die statische Hydrologie-Basis.

Große statische Geodaten werden hier nur aus lokalen Dateien verarbeitet. Der
Runtime-Betrieb führt keine automatischen Downloads von Flowlines/Basins aus.
Pegel können optional aus dem Kärnten-Hydro-JSON abgeleitet und lokal als
GeoJSON gespeichert werden.
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone
from typing import Any

import config
from hydro_station_index import build_station_index


def static_paths(static_dir: str | None = None) -> dict[str, str]:
    base = static_dir or getattr(config, "HYDRO_STATIC_DIR", "train_data/hydro/static")
    return {
        "base": base,
        "source": os.path.join(base, "source"),
        "generated": os.path.join(base, "generated"),
        "stations_source": os.path.join(base, "source", "hydro_stations.geojson"),
        "basins_source": os.path.join(base, "source", "basins.geojson"),
        "flowlines_source": os.path.join(base, "source", "flowlines.geojson"),
        "status": os.path.join(base, "generated", "hydro_static_status.json"),
    }


def ensure_static_dirs(static_dir: str | None = None) -> dict[str, str]:
    paths = static_paths(static_dir)
    for key in ("source", "generated"):
        os.makedirs(paths[key], exist_ok=True)
    return paths


def write_status(status: str, message: str, static_dir: str | None = None, **extra: Any) -> dict:
    paths = ensure_static_dirs(static_dir)
    payload = {"status": status, "message": message, "generated_at": datetime.now(timezone.utc).isoformat(), **extra}
    with open(paths["status"], "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return payload


def hydro_json_to_geojson(data: Any) -> dict:
    if isinstance(data, dict):
        rows = data.get("features") or data.get("stations") or data.get("data") or data.get("pegel") or []
    else:
        rows = data
    features = []
    for idx, row in enumerate(rows if isinstance(rows, list) else []):
        props = row.get("properties", row) if isinstance(row, dict) else {}
        geom = row.get("geometry") if isinstance(row, dict) else None
        lon = props.get("lon") or props.get("longitude") or props.get("lng") or props.get("x")
        lat = props.get("lat") or props.get("latitude") or props.get("y")
        if geom and geom.get("type") == "Point":
            lon, lat = geom.get("coordinates", [None, None])[:2]
        if lon is None or lat is None:
            continue
        station_id = props.get("station_id") or props.get("id") or props.get("number") or props.get("pegel_id") or str(idx + 1)
        out_props = dict(props)
        out_props.setdefault("station_id", str(station_id))
        out_props.setdefault("station_name", props.get("name") or props.get("station_name") or str(station_id))
        out_props.setdefault("river_name", props.get("river") or props.get("river_name") or props.get("gewaesser") or "")
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]}, "properties": out_props})
    return {"type": "FeatureCollection", "features": features}


def import_station_json(url: str | None = None, static_dir: str | None = None, timeout: int = 20) -> str:
    """Lädt nur das kleine Pegel-JSON und speichert daraus lokale Stationen."""
    paths = ensure_static_dirs(static_dir)
    with urllib.request.urlopen(url or config.HYDRO_STATIONS_URL, timeout=timeout) as response:  # nosec: konfigurierter Fach-Endpoint
        data = json.loads(response.read().decode("utf-8"))
    geojson = hydro_json_to_geojson(data)
    with open(paths["stations_source"], "w", encoding="utf-8") as f:
        json.dump(geojson, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return paths["stations_source"]


def build_static_hydro(static_dir: str | None = None) -> dict:
    paths = ensure_static_dirs(static_dir)
    missing = [name for name in ("stations_source", "basins_source") if not os.path.exists(paths[name])]
    if missing:
        return write_status("hydro_static_missing", "Statische Hydro-Eingangsdaten fehlen; Hydro-Impact ist noch nicht aktiv.", static_dir, missing=missing)
    return build_station_index(paths["stations_source"], paths["basins_source"], paths["flowlines_source"] if os.path.exists(paths["flowlines_source"]) else None, paths["generated"])


if __name__ == "__main__":
    print(json.dumps(build_static_hydro(), indent=2, ensure_ascii=False))
