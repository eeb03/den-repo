"""
SurveyFrame: one coherent acquisition unit -- a GPR line, a seismic shot
gather, a DEM tile, a magnetometer grid.

WHY THIS EXISTS
---------------
Survey-line identity is currently carried by `metadata["source_file"]` plus
`metadata["trace_index"]`: untyped strings that only work because
SEGYConverter happens to set them. They are load-bearing --
`_group_by_source_file`, `_reconstruct_traces_by_index` and
`find_anomaly_candidates` all depend on them -- and there is a real comment
in trace_processing.py explaining that trace_index is unique only WITHIN
one file, because grouping across files silently interleaved unrelated
survey lines into one fake trace.

A frame makes that identity explicit, and gives the constant-per-line
facts a home: which modality, which format, which CRS, what the vertical
axis measures, how positions were obtained, and what was assumed along the
way. Storing those once per line rather than once per record is not just
tidiness -- the INGV archive is 5.17 million records across 50 lines, so a
per-record CRS block would be five million copies of the same string.

This module is deliberately modality-AGNOSTIC. Nothing here knows what GPR
or seismic is; converters (modality-specific) construct frames, and the
rest of the platform consumes them uniformly.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from schemas.spatial import (
    AcquisitionElevationDatum, AffineTie, Assumption, GeoTie, SpatialRef, VerticalAxis,
)
from schemas.subterra_record import SensorType


def make_frame_id(dataset_id: str, source_file: str | Path) -> str:
    """
    Deterministic frame identity: ``{dataset_id}:{source_file_stem}``.

    Dataset-scoped rather than global, because a bare filename stem
    (`C1T_7,5_0001`) recurs across archives -- the INGV data ships three
    extracted copies of the same 50 lines. Scoping by dataset_id makes
    collisions impossible without making the id opaque; a content hash
    would also work but is far harder to read in a log or a test failure,
    and re-ingesting identical bytes into a new dataset should produce a
    new frame anyway.
    """
    return f"{dataset_id}:{Path(source_file).stem}"


class SurveyFrame(BaseModel):
    """
    Everything about one acquisition unit that does NOT vary sample to
    sample. Records reference it by `frame_id`.
    """

    frame_id: str
    dataset_id: str

    # --- what was measured, and by what ---
    modality: SensorType
    modality_source: str = "user_supplied"   # "user_supplied" | "file_header" | "inferred"

    # --- where it came from (provenance) ---
    source_format: str                        # converter.format_name: "segy", "geotiff", ...
    source_file: Optional[str] = None         # provenance only; identity is frame_id
    source_file_sha256: Optional[str] = None

    # --- how samples are positioned ---
    spatial_ref: SpatialRef
    vertical_axis: VerticalAxis
    n_positions: Optional[int] = None         # traces / stations / pixels
    position_index_name: str = "index"        # "trace_index" | "station" | "pixel"
    #: What the elevation STORED WITH THE SURVEY is measured from -- a different
    #: quantity from `vertical_axis`, and routinely a different datum. Absent
    #: means undeclared. Never inferred: an elevation that looks like a height
    #: above sea level is not evidence of a datum.
    acquisition_elevation_datum: Optional[AcquisitionElevationDatum] = None

    # --- how this frame relates to the Earth, when it does not on its own ---
    #: Absent means the frame is not georeferenced, which is a legitimate
    #: terminal state -- not a gap waiting to be filled with a guess.
    geo_tie: Optional[GeoTie] = None
    #: The 2D counterpart of `geo_tie`, for a frame whose native position is
    #: `LocalCartesianPosition` -- a real (x, y) with no along-track axis for
    #: a `GeoTie` to interpolate along. A frame carries at most one kind of
    #: tie in practice (its native position is exactly one `PositionKind`),
    #: but both fields exist because nothing here forbids a frame from
    #: having neither, or -- if its position kind changed across a
    #: correction -- from having both recorded historically.
    affine_tie: Optional[AffineTie] = None
    #: What `registered_position` is expressed in, once a tie has been
    #: applied. `spatial_ref` above continues to describe the ACQUISITION's
    #: own coordinates; the two coexist rather than one replacing the other.
    registered_spatial_ref: Optional[SpatialRef] = None

    # --- what we had to assume to produce any of the above ---
    assumptions: list[Assumption] = Field(default_factory=list)

    # --- the original header block, verbatim and unreduced ---
    source_metadata: dict[str, Any] = Field(default_factory=dict)

    def assumption(self, key: str) -> Optional[Assumption]:
        """Looks up one stated assumption by key, or None if it wasn't stated."""
        return next((a for a in self.assumptions if a.key == key), None)
