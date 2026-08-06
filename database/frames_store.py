"""
SurveyFrame storage, mirroring database/records_store.py.

Frames are small (one per survey line, ~50 for the whole INGV archive
against 5.17M records), so they are written as a single JSON document per
dataset alongside the record JSONL rather than into Postgres. Same seam,
same swap-later story as records_store.

`synthesize_frames_from_records` is the backward-compatibility path: every
dataset ingested before frames existed has records but no frame file, and
re-ingesting them is neither necessary nor cheap. It reconstructs a
best-effort frame from what the records already carry, and marks the
result as reconstructed so nothing mistakes an inference for a header.
"""
import json
from pathlib import Path

from configs.settings import settings
from schemas.spatial import Assumption, AxisKind, CRSKind, SpatialRef, VerticalAxis
from schemas.subterra_record import SubterraRecord
from schemas.survey_frame import SurveyFrame, make_frame_id


def _path_for(dataset_id: str) -> Path:
    return settings.processed_dir / f"{dataset_id}.frames.json"


def save_frames(dataset_id: str, frames: list[SurveyFrame]) -> Path:
    path = _path_for(dataset_id)
    with open(path, "w") as f:
        json.dump([fr.model_dump(mode="json") for fr in frames], f)
    return path


def load_frames(dataset_id: str) -> list[SurveyFrame]:
    """Returns [] when a dataset predates frames -- callers should fall back to synthesis."""
    path = _path_for(dataset_id)
    if not path.exists():
        return []
    with open(path) as f:
        return [SurveyFrame.model_validate(d) for d in json.load(f)]


def frames_by_id(frames: list[SurveyFrame]) -> dict[str, SurveyFrame]:
    return {fr.frame_id: fr for fr in frames}


def synthesize_frames_from_records(records: list[SubterraRecord]) -> list[SurveyFrame]:
    """
    Reconstructs one frame per distinct metadata["source_file"] for datasets
    ingested before frames existed.

    Everything here is inferred from record contents, never from the source
    file (which may no longer be on disk), so each frame carries an
    Assumption saying so. Fields that genuinely cannot be recovered --
    notably the spatial CRS, since records only ever stored bare
    lat/lon -- are left UNKNOWN rather than guessed.
    """
    if not records:
        return []

    by_file: dict[str, list[SubterraRecord]] = {}
    for r in records:
        by_file.setdefault(r.metadata.get("source_file", ""), []).append(r)

    frames = []
    for source_file, recs in sorted(by_file.items()):
        first = recs[0]
        meta = first.metadata

        # Position kinds actually present tell us more than the old lat/lon did.
        kinds = {r.position.kind for r in recs}
        if kinds == {"geographic"}:
            ref = SpatialRef(kind=CRSKind.GEOGRAPHIC, code="EPSG:4326", horizontal_units="deg",
                             name="reconstructed from stored record positions")
        elif kinds == {"projected"}:
            ref = SpatialRef(kind=CRSKind.PROJECTED, code=None, horizontal_units="m",
                             name="reconstructed from stored record positions; CRS never recorded")
        else:
            ref = SpatialRef(kind=CRSKind.UNKNOWN,
                             name=f"reconstructed; record position kinds present: {sorted(kinds)}")

        if meta.get("two_way_time_ns") is not None:
            axis = VerticalAxis(
                kind=AxisKind.TWO_WAY_TIME_NS, units="ns",
                origin="instrument time-zero at each trace", positive_down=True,
                n_samples=meta.get("sample_count"),
                conversion={
                    "method": "constant_velocity",
                    "velocity_m_per_ns": meta.get("velocity_m_per_ns"),
                    "formula": "depth_m = two_way_time_ns * velocity_m_per_ns / 2",
                    "target_axis": AxisKind.DEPTH_M.value,
                },
            )
        elif any(r.depth is not None for r in recs):
            axis = VerticalAxis(kind=AxisKind.DEPTH_M, units="m",
                                origin="unrecorded (reconstructed frame)", positive_down=True)
        else:
            axis = VerticalAxis(kind=AxisKind.NONE, units="",
                                origin="unrecorded (reconstructed frame)", positive_down=True)

        trace_indices = {r.metadata.get("trace_index") for r in recs}
        trace_indices.discard(None)

        frames.append(
            SurveyFrame(
                frame_id=first.frame_id or make_frame_id(first.dataset_id, source_file or "unknown"),
                dataset_id=first.dataset_id,
                modality=first.sensor_type,
                modality_source="inferred",
                source_format="unknown",
                source_file=source_file or None,
                spatial_ref=ref,
                vertical_axis=axis,
                n_positions=len(trace_indices) or None,
                position_index_name="trace_index" if trace_indices else "index",
                assumptions=[
                    Assumption(
                        key="frame_reconstructed", value=True,
                        basis="inferred from stored records; this dataset predates SurveyFrame",
                        verified=False,
                    )
                ],
                source_metadata={},
            )
        )
    return frames
