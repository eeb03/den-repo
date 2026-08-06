"""
Registry mapping file extensions to converters. New formats plug in here
without touching any other module (PRD: "easy to add new sensor types
without changing the core architecture").

This module is the SINGLE SOURCE OF TRUTH for which formats the platform
can read. `ingestion/downloader.py` previously kept its own hand-maintained
copy of the extension set, which had to be edited in two places and could
silently disagree with the registry; it now derives from here.

KNOWN_UNSUPPORTED_FORMATS is the explicit boundary for formats we recognise
but cannot yet read. Archive scanning used to drop these silently, so a zip
of proprietary GPR data looked indistinguishable from a zip containing
nothing of interest. Naming them lets ingestion say "this archive holds 40
IDS GeoRadar .dt files and no adapter exists" instead of "no supported
files found".
"""
from pathlib import Path

from converters.base import BaseConverter
from converters.csv_converter import CSVConverter
from converters.segy_converter import SEGYConverter
from converters.las_converter import LASConverter
from converters.geotiff_converter import GeoTIFFConverter
from converters.ids_dt_converter import IDSDTConverter
from converters.mala_converter import MALAConverter

_CONVERTERS: list[BaseConverter] = [
    CSVConverter(),
    SEGYConverter(),
    LASConverter(),
    GeoTIFFConverter(),
    IDSDTConverter(),
    MALAConverter(),
]

#: Formats we can NAME but not yet read. Being listed here is a promise that
#: ingestion will report the file explicitly rather than skip it in silence;
#: it is NOT a claim of support. A format graduates out of this map only when
#: a real file of that format has parsed and validated.
KNOWN_UNSUPPORTED_FORMATS: dict[str, str] = {
    ".dt_info": "IDS GeoRadar sidecar",
    # MALA sidecars. Named, not independently convertible: a .rad alone has no
    # samples and a .rd3 alone has no geometry, so the PAIR is the unit. Same
    # convention as .dt_info above.
    ".rad": "MALA RAMAC header sidecar (read with its .rd3/.rd7)",
    ".cor": "MALA RAMAC GNSS sidecar (read with its .rd3/.rd7)",
    ".mrk": "MALA RAMAC marker sidecar (not read)",
    ".add": "MALA RAMAC display-settings sidecar (not read)",
    ".em": "MALA RAMAC sidecar (not read)",
    ".dzt": "GSSI (proprietary GPR)",
    ".dzx": "GSSI sidecar",
    ".sgd": "Sensors & Software (proprietary GPR)",
    ".dzg": "GSSI GPS sidecar",
}


def supported_extensions() -> set[str]:
    """Every extension a registered converter can read. Computed live, so a
    converter added via `register_converter` is reflected immediately."""
    return {e for c in _CONVERTERS for e in c.supported_extensions}


def is_supported(path: str | Path) -> bool:
    return Path(path).suffix.lower() in supported_extensions()


def describe_unsupported(path: str | Path) -> str | None:
    """Human-readable format name if this is a RECOGNISED but unreadable
    format, else None (meaning: unknown/irrelevant, e.g. a readme)."""
    return KNOWN_UNSUPPORTED_FORMATS.get(Path(path).suffix.lower())


def classify_file(path: str | Path) -> tuple[str, str]:
    """
    Returns (classification, detail) where classification is one of
    "supported" | "recognized_unsupported" | "unknown".
    """
    p = Path(path)
    ext = p.suffix.lower()
    if ext in supported_extensions():
        return "supported", get_converter(p).format_name
    described = describe_unsupported(p)
    if described:
        return "recognized_unsupported", described
    return "unknown", ext or "(no extension)"


def get_converter(path: str | Path) -> BaseConverter:
    ext = Path(path).suffix.lower()
    for converter in _CONVERTERS:
        if ext in converter.supported_extensions:
            return converter
    described = describe_unsupported(path)
    if described:
        raise ValueError(
            f"'{ext}' is {described}. The platform recognises this format but has no "
            f"adapter for it yet, so the file cannot be read. Supported: {sorted(supported_extensions())}"
        )
    raise ValueError(
        f"No converter registered for extension '{ext}'. "
        f"Supported: {sorted(supported_extensions())}"
    )


def register_converter(converter: BaseConverter) -> None:
    """Plug in a new format converter at runtime."""
    _CONVERTERS.append(converter)
