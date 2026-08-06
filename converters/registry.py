"""
Registry mapping file extensions to converters. New formats plug in here
without touching any other module (PRD: "easy to add new sensor types
without changing the core architecture").
"""
from pathlib import Path

from converters.base import BaseConverter
from converters.csv_converter import CSVConverter
from converters.segy_converter import SEGYConverter
from converters.las_converter import LASConverter
from converters.geotiff_converter import GeoTIFFConverter

_CONVERTERS: list[BaseConverter] = [
    CSVConverter(),
    SEGYConverter(),
    LASConverter(),
    GeoTIFFConverter(),
]


def get_converter(path: str | Path) -> BaseConverter:
    ext = Path(path).suffix.lower()
    for converter in _CONVERTERS:
        if ext in converter.supported_extensions:
            return converter
    raise ValueError(
        f"No converter registered for extension '{ext}'. "
        f"Supported: {sorted({e for c in _CONVERTERS for e in c.supported_extensions})}"
    )


def register_converter(converter: BaseConverter) -> None:
    """Plug in a new format converter at runtime."""
    _CONVERTERS.append(converter)
