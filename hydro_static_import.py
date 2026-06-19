"""Import-Werkzeuge für die statische Hydrologie-Basis.

Große statische Geodaten werden hier nur aus lokalen Dateien verarbeitet. Der
Runtime-Betrieb führt keine automatischen Downloads von Flowlines/Basins aus.
Pegel können optional aus dem Kärnten-Hydro-JSON abgeleitet und lokal als
GeoJSON gespeichert werden.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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


def _is_http_url(source: str | None) -> bool:
    parsed = urlparse(source or "")
    return parsed.scheme in {"http", "https"}


def _read_station_source(source: str, timeout: int, allow_url_import: bool) -> Any:
    if _is_http_url(source):
        if not allow_url_import:
            raise ValueError("URL-Import ist nur für explizit manuell gestartete CLI-/Admin-Imports erlaubt.")
        from external_response_logger import persist_external_response, persist_requests_response
        from http_retry import retry_get

        try:
            response = retry_get(
                source,
                service="hydro_static_manual_import",
                timeout=timeout,
                max_retries=2,
                abort_on_4xx=True,
                breaker_service="hydro_static_manual_import",
            )
            persist_requests_response("hydro", "GET", response, fallback=False)
            return response.json()
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            body = None
            headers = None
            if getattr(exc, "response", None) is not None:
                try:
                    body = exc.response.text
                    headers = exc.response.headers
                except Exception:
                    pass
            persist_external_response(
                "hydro",
                url=source,
                method="GET",
                status_code=status,
                response_headers=headers,
                response_body=body,
                fallback=True,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise

    with open(Path(source), "r", encoding="utf-8") as f:
        return json.load(f)


def import_station_json(
    url: str | None = None,
    static_dir: str | None = None,
    timeout: int = 20,
    *,
    allow_url_import: bool = False,
) -> str:
    """Importiert Pegelstationen aus einer lokalen JSON-Datei.

    HTTP(S)-Quellen werden aus Sicherheitsgründen standardmäßig blockiert. Sie
    sind nur für explizit manuell gestartete CLI-/Admin-Imports erlaubt und
    laufen dann über den zentralen Retry- und Response-Logger.
    """
    paths = ensure_static_dirs(static_dir)
    source = url or getattr(config, "HYDRO_STATIONS_LOCAL_JSON", "")
    if not source:
        write_status("hydro_station_import_failed", "Keine lokale Pegel-JSON-Quelle angegeben.", static_dir)
        return ""

    try:
        data = _read_station_source(source, timeout, allow_url_import)
        geojson = hydro_json_to_geojson(data)
        with open(paths["stations_source"], "w", encoding="utf-8") as f:
            json.dump(geojson, f, indent=2, ensure_ascii=False)
            f.write("\n")
        write_status(
            "hydro_station_import_ok",
            "Statischer Hydro-Pegelimport abgeschlossen.",
            static_dir,
            source_type="url" if _is_http_url(source) else "local_file",
            station_count=len(geojson.get("features", [])),
        )
        return paths["stations_source"]
    except Exception as exc:
        write_status(
            "hydro_station_import_failed",
            f"Statischer Hydro-Pegelimport fehlgeschlagen: {type(exc).__name__}: {exc}",
            static_dir,
            source_type="url" if _is_http_url(source) else "local_file",
        )
        return ""


def build_static_hydro(static_dir: str | None = None) -> dict:
    paths = ensure_static_dirs(static_dir)
    missing = [name for name in ("stations_source", "basins_source") if not os.path.exists(paths[name])]
    if missing:
        return write_status("hydro_static_missing", "Statische Hydro-Eingangsdaten fehlen; Hydro-Impact ist noch nicht aktiv.", static_dir, missing=missing)
    return build_station_index(paths["stations_source"], paths["basins_source"], paths["flowlines_source"] if os.path.exists(paths["flowlines_source"]) else None, paths["generated"])


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Manuelle Werkzeuge für statische Hydro-Geodaten")
    parser.add_argument("--static-dir", default=None, help="Zielverzeichnis für statische Hydro-Daten")
    parser.add_argument("--import-stations", metavar="JSON", help="Lokale Pegel-JSON-Datei importieren")
    parser.add_argument(
        "--allow-url-import",
        action="store_true",
        help="HTTP(S)-Quelle explizit für einen manuellen CLI-Import freigeben",
    )
    args = parser.parse_args()

    if args.import_stations:
        path = import_station_json(args.import_stations, args.static_dir, allow_url_import=args.allow_url_import)
        if not path:
            return 1
    print(json.dumps(build_static_hydro(args.static_dir), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
