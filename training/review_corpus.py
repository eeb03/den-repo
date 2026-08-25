"""
Human-in-the-Loop Anomaly Verification V1: converts a `CandidateReview` (plus
the real signal window it addresses) into the EXISTING Real GPR Annotation
Corpus format (`schemas.segmentation.GPRTrainingExample`) -- Section 15's own
instruction: "Do not build a second annotation corpus." Every downstream
step (QA, manifest, visual overlay, site split) is `training.segmentation`'s
own, untouched, unduplicated.

WHY THE SIGNAL WINDOW IS A CALLER-SUPPLIED ARGUMENT, NOT FETCHED HERE. A live
dataset's real signal lives behind `preprocessing.spatial_grid.
build_trace_depth_grid_for_records`, which needs a DB session and the
dataset's stored records -- a live-API concern. This module stays a pure
converter (real geometry + real signal in, a real `GPRTrainingExample` out),
exactly the same separation `training.segmentation` itself keeps between its
own pure numpy logic and BAM's file-reading (`benchmark.bam_ingest`).
"""
from __future__ import annotations

from typing import Optional

from schemas.review import AnnotationGeometry, AnnotationGeometryKind, CandidateReview, ReviewStatus
from schemas.segmentation import GPRTrainingExample, LabelLevel, MaskRegion

REVIEW_PREPROCESSING_VERSION_PREFIX = "human-review-v1"


def geometry_to_mask_region(geometry: AnnotationGeometry,
                            window_trace_start: int, window_sample_start: int) -> MaskRegion:
    """
    Section 7's "annotation geometry -> deterministic width rule -> training
    mask", made explicit and reproducible:

      RIDGE_PATH  the traced points themselves, re-indexed to the window's
                  own local (0-based) coordinates -- IDENTITY, no width
                  added, mirroring `training.segmentation`'s own real-BAM
                  doctrine that a ridge pick claims exactly what was traced
                  and nothing more.
      RECTANGLE   every cell inside the reviewer's drawn box is positive --
                  not an invented width either: the reviewer marked the
                  whole extent, so the rule is "the box IS the region".

    Local indices are computed here (not stored on the geometry itself) so
    the same real geometry can be re-windowed if a future export uses a
    different window origin, without ever re-deriving the human's original
    marks.
    """
    if geometry.kind == AnnotationGeometryKind.RIDGE_PATH:
        return MaskRegion(
            trace_indices=[t - window_trace_start for t in geometry.trace_indices],
            sample_indices=[s - window_sample_start for s in geometry.sample_indices],
            rule="human-traced ridge/path, one sample per traced column, no invented width",
        )

    # RECTANGLE: every cell in the box.
    trace_indices, sample_indices = [], []
    for t in range(geometry.trace_start, geometry.trace_end + 1):
        for s in range(geometry.sample_start, geometry.sample_end + 1):
            trace_indices.append(t - window_trace_start)
            sample_indices.append(s - window_sample_start)
    return MaskRegion(
        trace_indices=trace_indices, sample_indices=sample_indices,
        rule="human-drawn rectangular region; every cell in the reviewer's own drawn "
             "extent is positive, no width beyond what was marked",
    )


def review_to_training_example(
    review: CandidateReview,
    signal: list[list[float]],
    window_trace_range: tuple[int, int],
    window_sample_range: tuple[int, int],
    preprocessing_version: str,
    sensor_vendor: Optional[str] = None,
    antenna_frequency_mhz: Optional[float] = None,
    sample_interval_ns: Optional[float] = None,
    license: Optional[str] = None,
    commercial_use_permitted: Optional[bool] = None,
) -> Optional[GPRTrainingExample]:
    """
    One reviewed candidate/missed-event -> one `GPRTrainingExample`, or
    `None` if the review is not corpus-eligible (`Section 15`: an UNREVIEWED
    review carries no human judgement to export).

    `mask=None` (a real, deliberate "labelled but no marked region") for a
    CONFIRMED/UNCERTAIN review with no `annotation_geometry` -- Section 4's
    own "critical valid state" (confirmed real, identity/extent unknown) is
    preserved rather than forced into a fabricated region. A REJECTED review
    is exported with an EMPTY mask (real negative evidence about the
    detector, not "no label") -- see module docstring on why this stays
    Grade C, never promoted to a verified-empty negative.
    """
    if not review.eligible_for_corpus:
        return None

    mask: Optional[MaskRegion] = None
    if review.review_status == ReviewStatus.REJECTED:
        mask = MaskRegion(trace_indices=[], sample_indices=[],
                          rule="reviewer rejected this candidate; real evidence about a "
                               "detector false positive, NOT a verified-empty ground truth")
    elif review.annotation_geometry is not None:
        mask = geometry_to_mask_region(
            review.annotation_geometry, window_trace_range[0], window_sample_range[0])

    label_level = LabelLevel.A_MASK if (mask and mask.n_cells > 0) else LabelLevel.D_EXISTENCE
    if review.review_status == ReviewStatus.REJECTED:
        label_level = LabelLevel.A_MASK  # an empty, but real and precisely-located, region

    basis_parts = [
        f"human-in-the-loop review, status={review.review_status.value}",
        f"reviewer={review.reviewer_id}",
    ]
    if review.operator_label:
        basis_parts.append(f"operator_label={review.operator_label} (human interpretation, not identity)")
    if review.is_missed_event:
        basis_parts.append("candidate-independent (missed-event) annotation: the detector never proposed this region")
    if review.notes:
        basis_parts.append(f"notes: {review.notes}")

    return GPRTrainingExample(
        dataset_id=review.dataset_id, site_id=review.site_id or review.dataset_id,
        survey_id=review.source_file, source_file=review.source_file,
        trace_range=(0, window_trace_range[1] - window_trace_range[0]),
        sample_range=(0, window_sample_range[1] - window_sample_range[0]),
        signal=signal, mask=mask, label_level=label_level,
        label_source=review.label_source, evidence_grade=review.evidence_grade,
        label_basis="; ".join(basis_parts),
        sensor_vendor=sensor_vendor, antenna_frequency_mhz=antenna_frequency_mhz,
        sample_interval_ns=sample_interval_ns,
        preprocessing_version=f"{REVIEW_PREPROCESSING_VERSION_PREFIX}-{preprocessing_version}",
        license=license, commercial_use_permitted=commercial_use_permitted,
        extra={"review_id": review.id, "candidate_id": review.candidate_id,
               "review_status": review.review_status.value},
    )
