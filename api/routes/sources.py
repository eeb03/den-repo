from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ingestion.sources import SOURCE_REGISTRY, SourceAPIError, OpenTopographyConnector, USGSConnector

router = APIRouter()


@router.get("/{source_name}/search")
def search_source(source_name: str, q: str = Query(..., description="Search query"), limit: int = 10):
    connector = SOURCE_REGISTRY.get(source_name)
    if not connector:
        raise HTTPException(status_code=404, detail=f"Unknown source '{source_name}'. Options: {list(SOURCE_REGISTRY)}")
    try:
        results = connector.search(q, limit=limit)
    except SourceAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return [
        {
            "title": r.title, "source": r.source, "download_url": r.download_url,
            "license": r.license, "description": r.description, "extra": r.extra,
        }
        for r in results
    ]


@router.get("/opentopography/dem")
def fetch_opentopography_dem(
    dem_type: str,
    south: float, north: float, west: float, east: float,
    usgs: bool = False,
    output_format: str = "GTiff",
):
    """Fetch a DEM tile for a bounding box. Set usgs=true for USGS 3DEP types (USGS30m/10m/1m)."""
    connector: OpenTopographyConnector = SOURCE_REGISTRY["opentopography"]
    try:
        if usgs:
            path = connector.get_usgs_dem(dem_type, south, north, west, east, output_format)
        else:
            path = connector.get_global_dem(dem_type, south, north, west, east, output_format)
    except (ValueError, SourceAPIError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"saved_to": str(path), "size_bytes": path.stat().st_size}


@router.get("/usgs/earthquakes")
def fetch_usgs_earthquakes(
    min_lat: float, max_lat: float, min_lon: float, max_lon: float,
    start_time: Optional[str] = None, end_time: Optional[str] = None,
    min_magnitude: Optional[float] = None, limit: int = 100,
):
    connector: USGSConnector = SOURCE_REGISTRY["usgs"]
    try:
        results = connector.get_earthquakes_in_bbox(
            min_lat, max_lat, min_lon, max_lon, start_time, end_time, min_magnitude, limit
        )
    except SourceAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return [{"title": r.title, "extra": r.extra} for r in results]
