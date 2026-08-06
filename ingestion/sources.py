"""
Dataset source connectors — real implementations against public APIs.

Each connector's `search(query)` does best-effort discovery. Note that not
every source is a free-text search engine: OpenTopography's global/USGS DEM
services are bounding-box + dataset-type based, not keyword search, so their
`search()` matches against known dataset type names/descriptions and the
*real* data retrieval happens through the dedicated typed methods below it
(`get_global_dem`, `get_usgs_dem`, `get_earthquakes_in_bbox`). Zenodo is the
one source here with genuine full-text search.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

import requests

from configs.settings import settings
from ingestion.downloader import download_file
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class SourceSearchResult:
    title: str
    source: str
    download_url: str
    license: str | None = None
    description: str | None = None
    checksum: str | None = None
    extra: dict = field(default_factory=dict)


class BaseSourceConnector(ABC):
    source_name: str = "base"

    @abstractmethod
    def search(self, query: str, limit: int = 10) -> list[SourceSearchResult]:
        raise NotImplementedError


class SourceAPIError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Zenodo — https://developers.zenodo.org/
# --------------------------------------------------------------------------
class ZenodoConnector(BaseSourceConnector):
    """
    Full-text search over Zenodo's published records. Anonymous requests are
    capped at 25 results/page; set ZENODO_ACCESS_TOKEN to raise that to 100
    and avoid aggressive rate limiting.
    """
    source_name = "zenodo"
    BASE_URL = "https://zenodo.org/api/records"

    def search(self, query: str, limit: int = 10) -> list[SourceSearchResult]:
        params = {"q": query, "size": min(limit, 25 if not settings.zenodo_access_token else 100)}
        headers = {}
        if settings.zenodo_access_token:
            headers["Authorization"] = f"Bearer {settings.zenodo_access_token}"

        try:
            resp = requests.get(self.BASE_URL, params=params, headers=headers, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise SourceAPIError(f"Zenodo search failed: {e}") from e

        data = resp.json()
        results: list[SourceSearchResult] = []
        for hit in data.get("hits", {}).get("hits", [])[:limit]:
            metadata = hit.get("metadata", {})
            files = hit.get("files", []) or []
            download_url = files[0]["links"]["self"] if files and "links" in files[0] else hit.get("links", {}).get("self", "")
            license_info = metadata.get("license", {})
            results.append(
                SourceSearchResult(
                    title=metadata.get("title", "Untitled"),
                    source="zenodo",
                    download_url=download_url,
                    license=license_info.get("id") if isinstance(license_info, dict) else license_info,
                    description=metadata.get("description"),
                    extra={
                        "record_id": hit.get("id"),
                        "doi": hit.get("doi"),
                        "file_count": len(files),
                        "all_files": [
                            {"filename": f.get("key"), "url": f.get("links", {}).get("self"), "size": f.get("size")}
                            for f in files
                        ],
                    },
                )
            )

        logger.info(f"Zenodo search '{query}': {len(results)} result(s)")
        return results

    def download_record_files(self, result: SourceSearchResult) -> list[Path]:
        """Download every file attached to a Zenodo search result."""
        paths = []
        for f in result.extra.get("all_files", []):
            if f.get("url"):
                paths.append(download_file(f["url"], dest_filename=f.get("filename")))
        return paths


# --------------------------------------------------------------------------
# OpenTopography — https://portal.opentopography.org/apidocs/
# --------------------------------------------------------------------------
class OpenTopographyConnector(BaseSourceConnector):
    """
    OpenTopography serves DEMs by bounding box + dataset type rather than
    free text, so `search()` matches the query against known dataset type
    names/descriptions to help pick a `demtype`. Use `get_global_dem` or
    `get_usgs_dem` to actually fetch data for a bounding box.
    """
    source_name = "opentopography"
    BASE_URL = "https://portal.opentopography.org/API"

    GLOBAL_DEM_TYPES = {
        "SRTMGL3": "SRTM GL3 (Global 90m)",
        "SRTMGL1": "SRTM GL1 (Global 30m)",
        "SRTMGL1_E": "SRTM GL1 Ellipsoidal (Global 30m)",
        "AW3D30": "ALOS World 3D (Global 30m)",
        "AW3D30_E": "ALOS World 3D Ellipsoidal (Global 30m)",
        "SRTM15Plus": "Global Bathymetry SRTM15+ V2.1",
        "NASADEM": "NASADEM Global DEM",
        "COP30": "Copernicus Global DSM 30m",
        "COP90": "Copernicus Global DSM 90m",
        "EU_DTM": "Continental Europe Digital Terrain Model 30m",
        "GEDI_L3": "GEDI L3 DTM 1000m",
        "GEBCOIceTopo": "Global Bathymetry 500m (Ice Surface)",
        "GEBCOSubIceTopo": "Global Bathymetry 500m (Sub-Ice)",
        "CA_MRDEM_DSM": "Canada Medium Resolution DEM (Surface)",
        "CA_MRDEM_DTM": "Canada Medium Resolution DEM (Terrain)",
    }
    USGS_DEM_TYPES = {
        "USGS30m": "USGS 3DEP 1 arc-second (~30m)",
        "USGS10m": "USGS 3DEP 1/3 arc-second (~10m)",
        "USGS1m": "USGS 3DEP 1m (academic access only)",
    }

    def search(self, query: str, limit: int = 10) -> list[SourceSearchResult]:
        q = query.lower()
        all_types = {**self.GLOBAL_DEM_TYPES, **self.USGS_DEM_TYPES}
        matches = [
            (code, desc) for code, desc in all_types.items()
            if q in code.lower() or q in desc.lower()
        ][:limit]

        return [
            SourceSearchResult(
                title=desc,
                source="opentopography",
                download_url="",  # bbox required; see get_global_dem/get_usgs_dem
                description=f"Dataset type '{code}'. Call get_global_dem()/get_usgs_dem() with a bounding box to retrieve.",
                extra={"dem_type": code},
            )
            for code, desc in matches
        ]

    def get_global_dem(
        self, dem_type: str, south: float, north: float, west: float, east: float,
        output_format: str = "GTiff", dest_filename: str | None = None,
    ) -> Path:
        if dem_type not in self.GLOBAL_DEM_TYPES:
            raise ValueError(f"Unknown global demtype '{dem_type}'. Options: {list(self.GLOBAL_DEM_TYPES)}")
        return self._fetch_dem("globaldem", {"demtype": dem_type}, south, north, west, east, output_format, dest_filename)

    def get_usgs_dem(
        self, dem_type: str, south: float, north: float, west: float, east: float,
        output_format: str = "GTiff", dest_filename: str | None = None,
    ) -> Path:
        if dem_type not in self.USGS_DEM_TYPES:
            raise ValueError(f"Unknown USGS demtype '{dem_type}'. Options: {list(self.USGS_DEM_TYPES)}")
        return self._fetch_dem("usgsdem", {"datasetName": dem_type}, south, north, west, east, output_format, dest_filename)

    def _fetch_dem(
        self, endpoint: str, type_param: dict, south: float, north: float,
        west: float, east: float, output_format: str, dest_filename: str | None,
    ) -> Path:
        if not settings.opentopography_api_key:
            raise SourceAPIError(
                "OPENTOPOGRAPHY_API_KEY is not set. Request a free key at "
                "https://portal.opentopography.org/myopentopo and add it to .env"
            )
        params = {
            **type_param,
            "south": south, "north": north, "west": west, "east": east,
            "outputFormat": output_format,
            "API_Key": settings.opentopography_api_key,
        }
        url = f"{self.BASE_URL}/{endpoint}"
        try:
            resp = requests.get(url, params=params, timeout=120)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise SourceAPIError(f"OpenTopography {endpoint} request failed: {e}") from e

        ext = {"GTiff": "tif", "AAIGrid": "asc", "HFA": "img"}.get(output_format, "tif")
        filename = dest_filename or f"{type_param.get('demtype') or type_param.get('datasetName')}_{south}_{west}_{north}_{east}.{ext}"
        out_path = settings.downloads_dir / filename
        out_path.write_bytes(resp.content)
        logger.info(f"OpenTopography: saved {filename} ({len(resp.content)} bytes)")
        return out_path


# --------------------------------------------------------------------------
# USGS — earthquake catalog (FDSN event service) is the stable, keyless,
# well-documented USGS API most relevant to ground-truth/seismic context.
# https://earthquake.usgs.gov/fdsnws/event/1/
# --------------------------------------------------------------------------
class USGSConnector(BaseSourceConnector):
    """
    Searches the USGS earthquake catalog. `query` is treated as a minimum-
    magnitude threshold if numeric (e.g. "4.5"), otherwise it's ignored and
    results are the most recent events — the FDSN event API is
    parametric (time/bbox/magnitude), not full-text.
    """
    source_name = "usgs"
    BASE_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"

    def search(self, query: str, limit: int = 10) -> list[SourceSearchResult]:
        params = {"format": "geojson", "limit": limit, "orderby": "time"}
        try:
            min_mag = float(query)
            params["minmagnitude"] = min_mag
        except (ValueError, TypeError):
            pass  # non-numeric query: just return recent events

        try:
            resp = requests.get(self.BASE_URL, params=params, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise SourceAPIError(f"USGS earthquake search failed: {e}") from e

        features = resp.json().get("features", [])
        results = []
        for f in features:
            props = f.get("properties", {})
            geom = f.get("geometry", {})
            coords = geom.get("coordinates", [None, None, None])
            results.append(
                SourceSearchResult(
                    title=props.get("title", "Unnamed event"),
                    source="usgs",
                    download_url=props.get("detail", ""),
                    license="public domain (USGS)",
                    description=f"Magnitude {props.get('mag')} at depth {coords[2]}km",
                    extra={
                        "longitude": coords[0], "latitude": coords[1], "depth_km": coords[2],
                        "magnitude": props.get("mag"), "time_ms": props.get("time"),
                    },
                )
            )

        logger.info(f"USGS earthquake search: {len(results)} result(s)")
        return results

    def get_earthquakes_in_bbox(
        self, min_lat: float, max_lat: float, min_lon: float, max_lon: float,
        start_time: str | None = None, end_time: str | None = None,
        min_magnitude: float | None = None, limit: int = 100,
    ) -> list[SourceSearchResult]:
        """Real bbox+time+magnitude filtered query, for when you know exactly what you want."""
        params = {
            "format": "geojson", "limit": limit,
            "minlatitude": min_lat, "maxlatitude": max_lat,
            "minlongitude": min_lon, "maxlongitude": max_lon,
        }
        if start_time:
            params["starttime"] = start_time
        if end_time:
            params["endtime"] = end_time
        if min_magnitude is not None:
            params["minmagnitude"] = min_magnitude

        try:
            resp = requests.get(self.BASE_URL, params=params, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise SourceAPIError(f"USGS bbox query failed: {e}") from e

        results = []
        for f in resp.json().get("features", []):
            props, geom = f.get("properties", {}), f.get("geometry", {})
            coords = geom.get("coordinates", [None, None, None])
            results.append(
                SourceSearchResult(
                    title=props.get("title", "Unnamed event"), source="usgs",
                    download_url=props.get("detail", ""), license="public domain (USGS)",
                    extra={
                        "longitude": coords[0], "latitude": coords[1], "depth_km": coords[2],
                        "magnitude": props.get("mag"), "time_ms": props.get("time"),
                    },
                )
            )
        return results


SOURCE_REGISTRY: dict[str, BaseSourceConnector] = {
    "zenodo": ZenodoConnector(),
    "opentopography": OpenTopographyConnector(),
    "usgs": USGSConnector(),
}
