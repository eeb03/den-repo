"""
Learned Detector V1: dataset construction, site-level splitting, evaluation
metrics, and a baseline-comparison harness -- the "reusable dataset/training
infrastructure" the milestone brief calls for when real labels are
insufficient to train on (see this module's own AUDIT section below).
Deliberately holds NO PyTorch/model code: everything here runs on numpy
alone, so it stays testable and usable even where the optional learned-model
dependency (`training.segmentation_model`) is not installed.

============================================================================
THE AUDIT THIS MODULE IS BUILT AGAINST (do not build past what it found)
============================================================================

Before writing this module, every held GPR dataset's own truth/target file
was read directly (not assumed from a doc's summary of it) and scored
against the milestone's own Level A-D rubric:

  BAM     -- 1 specimen (Pk266) with 4 real, discrete, trace-associated
             targets. `benchmark.bam_truth.build_footprint` gives a REAL,
             code-verified, deterministic X-axis trace footprint per target
             (Level B). A real per-trace TIME-axis pick exists ONLY where
             `scripts.bam_hyperbola_velocity_audit.associate_target`'s own
             confidence gate is cleared -- a DERIVED measurement (this
             session's own real signal, not published truth), never
             promoted to "measured ground truth". Pk050 is a real,
             fabricator-attested EMPTY specimen (a genuine negative).
             Pk401's targets exist only in an un-digitised drawing appendix
             and are correctly left untranscribed.
  4TU     -- Level D. Truth is a per-activity utility COUNT; the publisher
             withholds trench coordinates outright. Zero mechanical path to
             a trace association exists -- not a gap that more code could
             close.
  TU1208  -- Level D. Depth-only; `transverse_offset_m` is published for
             zero of 36 targets (checked directly against the transcribed
             file, not assumed). No X position exists to associate a trace
             with.
  TestUM  -- Level D. What is surveyed (a freezing front) is a diffuse,
             time-varying CONDITION, not a discrete object -- there is no
             object-level truth to associate regardless of trace access.
  Grimsel -- Not held. The geological-model toolkit was read once and
             deleted per its own licence; no raw GPR or target file remains
             in this repo to inspect further.

TOTAL REAL, TRACE-ASSOCIATED TARGETS ACROSS THE ENTIRE HELD CORPUS: 4. All
four in ONE specimen. This is not enough to define a physically meaningful
site-level train/validation/test split (Phase 7 of the brief) by
construction -- there is only one site with any usable label at all -- and
nowhere near enough for a statistically meaningful segmentation-training
claim. Per the brief's own Section 32 ("If there is not enough real
labelled data... DO NOT fabricate labels. Instead implement only the
reusable dataset/training infrastructure"), THIS MODULE STOPS THERE: it
builds and tests the dataset/split/metric/comparison machinery so it can
honestly support real labels the moment more exist, and it does NOT run,
and this repository does NOT claim, a validated Detector V1 training
result. See `docs/roadmap.md` and the milestone's own final report for the
exact annotation deficit this leaves.

============================================================================
INPUT REPRESENTATION
============================================================================

BAM's real signal is read directly from `benchmark.bam_ingest` (the
already-trusted reader `scripts.bam_hyperbola_velocity_audit` itself uses)
-- NOT through `preprocessing.spatial_grid.build_trace_depth_grid_for_records`,
because the BAM benchmark archive has never been ingested into the live
`SubterraRecord` pipeline (confirmed: no route or converter calls
`database.objects_store`/`database.records_store` for it). For a FUTURE
live-ingested dataset with real labels, `build_trace_depth_grid_for_records`
is the equivalent, already-live mechanism a caller should reach for
instead -- the same (depth, trace) index convention is used here
specifically so that swap is straightforward later.

The window handed to `signal` is the SAME central-Y-band-averaged window
`associate_target` itself computed to make its picks (see
`_bam_target_window` below, which mirrors -- not duplicates the intent of
-- that function's internal averaging so the mask and the signal it was
picked from are guaranteed mutually consistent). This is real, PROCESSED
(not raw) amplitude: BAM's own archive supplies no separate raw trace, and
`scripts.bam_hyperbola_velocity_audit.establish_time_axis` is what already
establishes this data's time axis, reused verbatim here.

============================================================================
WHY THE MASK IS A ONE-SAMPLE-WIDE RIDGE, NOT AN INVENTED-WIDTH BLOB
============================================================================

`associate_target`'s ridge-tracked `curve` gives ONE measured sample index
per traced column -- the picked arrival, gated by confidence. Widening that
into a thicker band (to better resemble a real reflector's finite pulse
duration) would need a real, evidence-based width, and none is established
anywhere in this codebase for a DUCT REFLECTION specifically (the "40+
samples" figure elsewhere in this session characterises the DIRECT/COUPLING
arrival's own ringdown at 2.6 GHz, a different signal, not reusable here
without inventing a new number). So the mask claims exactly what was
measured -- one sample, per traced column -- and nothing more. Widening it
defensibly is exactly the kind of real annotation work this module's audit
reports as missing, not a decision this module makes unilaterally.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from benchmark import bam_ingest, bam_truth
from schemas.segmentation import (
    TRAINABLE_LABEL_LEVELS,
    GPRTrainingExample,
    LabelLevel,
    LabelSource,
    MaskRegion,
)
from scripts.bam_hyperbola_velocity_audit import (
    DEFAULT_APERTURE_MM,
    DEFAULT_Y_MARGIN_MM,
    associate_target,
    establish_time_axis,
    load_targets as load_velocity_audit_targets,
)

PREPROCESSING_VERSION = "bam-ingest-central-y-average-v1"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BAM_ROOT = REPO_ROOT / bam_ingest.DEFAULT_ROOT


# ---------------------------------------------------------------------------
# dataset construction -- REAL BAM data only
# ---------------------------------------------------------------------------

def _bam_target_window(grid, volume, x0: int, aperture_mm: float, y_margin_mm: float):
    """
    The exact central-Y-band-averaged (n_x_window, n_samples) window
    `associate_target` computes internally to make its picks -- mirrored
    here (not imported) because `associate_target` does not return it, and
    changing that already-verified function's signature to expose it risks
    disturbing this session's own pinned real-data velocity-audit results.
    Kept to the same few lines, same formulas, same variable names as the
    original, so the two stay checkable against each other by inspection.
    """
    half = int(round(aperture_mm / grid.x_step))
    x_lo, x_hi = max(0, x0 - half), min(grid.x.size - 1, x0 + half)
    y_lo_mm, y_hi_mm = y_margin_mm, float(grid.y[-1]) - y_margin_mm
    y_indices = [i for i, y in enumerate(grid.y) if y_lo_mm <= y <= y_hi_mm]
    window = volume[x_lo:x_hi + 1, :, :][:, y_indices, :].mean(axis=1)
    return window, x_lo, x_hi


def build_bam_pk266_examples(
    scan_id: str = "Pk266_3D_Dataset_2_6_GHz_Rot00",
    aperture_mm: float = DEFAULT_APERTURE_MM,
    y_margin_mm: float = DEFAULT_Y_MARGIN_MM,
    root: Path = DEFAULT_BAM_ROOT,
) -> list[GPRTrainingExample]:
    """
    The entire real, trace-associated positive-label corpus this milestone
    found: 4 BAM Pk266 targets, each an example IF AND ONLY IF a real
    arrival-time pick cleared `associate_target`'s own confidence gate --
    never a guessed mask for a target whose pick failed. See this module's
    own docstring for the full audit and why this is the corpus, not a
    sample of a larger one.
    """
    scan = bam_ingest.load_scan("Pk266", scan_id, root=root)
    volume = bam_ingest.load_volume(scan, root=root)
    time_axis = establish_time_axis(scan)
    targets = load_velocity_audit_targets()

    examples = []
    for target in targets:
        assoc = associate_target(target, scan.grid, volume, time_axis, aperture_mm, y_margin_mm)
        if not assoc.usable or assoc.apex_pick is None or not assoc.curve:
            # No guessed mask for a target whose real pick did not clear
            # the confidence gate -- reported as a real, honest omission,
            # not silently dropped: the caller sees fewer examples than
            # targets, and that count IS the finding.
            continue

        x0 = assoc.x_node
        window, x_lo, x_hi = _bam_target_window(scan.grid, volume, x0, aperture_mm, y_margin_mm)
        signal = window.T.tolist()  # (n_samples, n_x_window), matching MaskRegion's convention

        trace_indices = [p.x_mm for p in assoc.curve]
        trace_indices = [scan.grid.x_node(x) - x_lo for x in trace_indices]  # window-local index
        sample_indices = [p.sample_index for p in assoc.curve]
        mask = MaskRegion(
            trace_indices=trace_indices, sample_indices=sample_indices,
            rule=(
                "one sample per real ridge-tracked arrival-time pick "
                "(scripts.bam_hyperbola_velocity_audit.associate_target), gated by "
                f"MIN_PICK_CONFIDENCE; no invented width around the pick"
            ),
        )

        examples.append(GPRTrainingExample(
            dataset_id=f"bam-{scan.specimen_id}",
            site_id=scan.specimen_id,
            survey_id=scan_id,
            source_file=scan.archive,
            trace_range=(0, window.shape[0] - 1),
            sample_range=(0, window.shape[1] - 1),
            signal=signal,
            mask=mask,
            label_level=LabelLevel.A_MASK if len(mask.trace_indices) > 0 else LabelLevel.B_REGION,
            label_source=LabelSource.MEASURED_ASSOCIATION,
            label_basis=(
                f"target {target.target_id}: real X footprint from "
                f"benchmark.bam_truth.build_footprint (published X {target.x_mm} mm, "
                f"outer diameter from benchmark/bam_pk266_targets.json, "
                f"transcribed_from_publication), real per-trace arrival time from "
                f"scripts.bam_hyperbola_velocity_audit.associate_target "
                f"(confidence >= its own MIN_PICK_CONFIDENCE threshold)"
            ),
            sensor_vendor="GSSI",
            antenna_frequency_mhz=2600.0 if "2_6_GHz" in scan_id else 1500.0,
            sample_interval_ns=time_axis.sample_interval_ns,
            preprocessing_version=PREPROCESSING_VERSION,
            extra={"target_id": target.target_id, "n_traced_picks": len(assoc.curve)},
        ))
    return examples


def build_bam_pk050_negative_examples(
    scan_id: str = "Pk050_3D_Dataset_2_6_GHz_Rot00",
    root: Path = DEFAULT_BAM_ROOT,
) -> list[GPRTrainingExample]:
    """
    Pk050: a REAL, fabricator-attested empty specimen -- see
    `benchmark.bam_truth.load_control`'s own `attestation`. Genuine negative
    evidence, distinct from "unlabelled": the mask is an empty `MaskRegion`
    (not `None`), because the absence of a target here is itself an
    asserted fact, not a missing one. The step back walls ARE real
    reflectors (`load_control`'s own `caveat`) -- this controls for
    embedded objects, not for "no signal at all".
    """
    scan = bam_ingest.load_scan("Pk050", scan_id, root=root)
    volume = bam_ingest.load_volume(scan, root=root)
    time_axis = establish_time_axis(scan)
    control = bam_truth.load_control("Pk050")

    n_x = scan.grid.x.size
    window = volume[:, :, :].mean(axis=1)  # full width, central average not needed (whole specimen is control)
    signal = window.T.tolist()

    return [GPRTrainingExample(
        dataset_id=f"bam-{scan.specimen_id}",
        site_id=scan.specimen_id,
        survey_id=scan_id,
        source_file=scan.archive,
        trace_range=(0, n_x - 1),
        sample_range=(0, window.shape[1] - 1),
        signal=signal,
        mask=MaskRegion(trace_indices=[], sample_indices=[],
                        rule="empty by fabricator attestation, not an absence of evidence"),
        label_level=LabelLevel.A_MASK,
        label_source=LabelSource.PUBLISHED_TRUTH,
        label_basis=f"{control.attestation} Caveat: {control.caveat}",
        sensor_vendor="GSSI",
        antenna_frequency_mhz=2600.0 if "2_6_GHz" in scan_id else 1500.0,
        sample_interval_ns=time_axis.sample_interval_ns,
        preprocessing_version=PREPROCESSING_VERSION,
        extra={"attested_empty": True},
    )]


# ---------------------------------------------------------------------------
# site-level split -- leakage-aware by construction
# ---------------------------------------------------------------------------

def split_by_site(
    examples: list[GPRTrainingExample],
    train_sites: set,
    validation_sites: set,
    test_sites: set,
) -> list[GPRTrainingExample]:
    """
    Assigns `example.split` by `site_id` membership, refusing (not
    guessing) anything ambiguous. NEVER a trace-level or example-level
    random split -- see this module's own docstring on why: neighbouring
    windows of the same real target can be nearly identical, and a random
    split can put near-duplicates on both sides, which is leakage the
    milestone brief explicitly forbids presenting as evidence of
    generalisation.

    Every one of `train_sites`/`validation_sites`/`test_sites` must be
    disjoint from the other two -- checked, not assumed, because a site
    accidentally listed twice would silently leak.
    """
    overlaps = [
        (a_name, b_name, a & b)
        for a_name, a in (("train", train_sites), ("validation", validation_sites), ("test", test_sites))
        for b_name, b in (("train", train_sites), ("validation", validation_sites), ("test", test_sites))
        if a_name < b_name and (a & b)
    ]
    if overlaps:
        raise ValueError(f"site sets are not disjoint: {overlaps}")

    out = []
    for ex in examples:
        if ex.site_id in train_sites:
            split = "train"
        elif ex.site_id in validation_sites:
            split = "validation"
        elif ex.site_id in test_sites:
            split = "test"
        else:
            raise ValueError(
                f"example from site {ex.site_id!r} is not assigned to train, validation or "
                f"test -- every site must be explicitly placed, never defaulted"
            )
        out.append(ex.model_copy(update={"split": split}))
    return out


@dataclass(frozen=True)
class SplitAdequacy:
    """Whether a split is strong enough to support a generalisation claim -- computed, not assumed."""
    n_train_sites: int
    n_validation_sites: int
    n_test_sites: int
    adequate: bool
    reason: str


def assess_split_adequacy(
    train_sites: set, validation_sites: set, test_sites: set, min_sites_per_split: int = 1,
) -> SplitAdequacy:
    """
    The brief's own instruction: "If there are too few sites... document
    the weakness." This function is that documentation, computed rather
    than asserted in prose that could drift from the real site count.
    `min_sites_per_split=1` is deliberately permissive (a single-site split
    IS constructible) -- `adequate=False` still fires whenever any split
    has fewer than 2 sites, since a true generalisation claim needs a real
    held-out SITE, and 1 vs 1 cannot distinguish "this model generalises"
    from "this model memorised the one site it saw".
    """
    counts = (len(train_sites), len(validation_sites), len(test_sites))
    adequate = all(c >= 2 for c in counts)
    reason = (
        "at least 2 sites per split -- a genuine generalisation claim is supportable"
        if adequate else
        f"train/validation/test sites = {counts}; fewer than 2 sites in at least one split "
        f"means a result here cannot be distinguished from memorising the one site tested, "
        f"and must not be reported as evidence of cross-site generalisation"
    )
    return SplitAdequacy(*counts, adequate=adequate, reason=reason)


# ---------------------------------------------------------------------------
# evaluation metrics -- real implementations, hand-verifiable
# ---------------------------------------------------------------------------

def _mask_to_dense(mask: Optional[MaskRegion], shape: tuple[int, int]) -> np.ndarray:
    """(n_samples, n_traces) boolean array. `None` mask -> all False (unlabelled, not negative)."""
    dense = np.zeros(shape, dtype=bool)
    if mask is None:
        return dense
    for t, s in zip(mask.trace_indices, mask.sample_indices):
        if 0 <= s < shape[0] and 0 <= t < shape[1]:
            dense[s, t] = True
    return dense


def dice_coefficient(pred: np.ndarray, truth: np.ndarray) -> Optional[float]:
    """2|P∩T| / (|P|+|T|). None (not 0.0 or 1.0) when both are empty -- undefined, not perfect."""
    p, t = pred.astype(bool), truth.astype(bool)
    if not p.any() and not t.any():
        return None
    intersection = np.logical_and(p, t).sum()
    return float(2 * intersection / (p.sum() + t.sum()))


def iou(pred: np.ndarray, truth: np.ndarray) -> Optional[float]:
    """|P∩T| / |P∪T|. None when both are empty -- undefined, not perfect."""
    p, t = pred.astype(bool), truth.astype(bool)
    union = np.logical_or(p, t).sum()
    if union == 0:
        return None
    return float(np.logical_and(p, t).sum() / union)


@dataclass(frozen=True)
class PrecisionRecall:
    precision: Optional[float]
    recall: Optional[float]
    f1: Optional[float]
    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int


def precision_recall_f1(pred: np.ndarray, truth: np.ndarray) -> PrecisionRecall:
    p, t = pred.astype(bool), truth.astype(bool)
    tp = int(np.logical_and(p, t).sum())
    fp = int(np.logical_and(p, ~t).sum())
    fn = int(np.logical_and(~p, t).sum())
    tn = int(np.logical_and(~p, ~t).sum())
    precision = tp / (tp + fp) if (tp + fp) > 0 else None
    recall = tp / (tp + fn) if (tp + fn) > 0 else None
    f1 = (2 * precision * recall / (precision + recall)
         if precision is not None and recall is not None and (precision + recall) > 0 else None)
    return PrecisionRecall(precision, recall, f1, tp, fp, fn, tn)


def pr_auc(scores: np.ndarray, truth: np.ndarray) -> Optional[float]:
    """
    Trapezoidal area under the precision-recall curve, swept over every
    distinct score as a threshold. `None` if `truth` has no positives at
    all (a PR curve is undefined with nothing to recall).
    """
    t = truth.astype(bool)
    if not t.any():
        return None
    order = np.argsort(-scores)
    scores_sorted, t_sorted = scores[order], t[order]
    tp = np.cumsum(t_sorted)
    fp = np.cumsum(~t_sorted)
    n_pos = t.sum()
    recall = tp / n_pos
    precision = tp / np.maximum(tp + fp, 1)
    # prepend the (recall=0) point at precision=1 by convention, matching
    # the standard PR-AUC definition (no positives predicted yet).
    recall = np.concatenate([[0.0], recall])
    precision = np.concatenate([[1.0], precision])
    return float(np.trapezoid(precision, recall))


def false_positives_per_metre(pred: np.ndarray, truth: np.ndarray, trace_spacing_m: float) -> Optional[float]:
    """
    False positive TRACE COLUMNS (any false-positive sample in that
    column counts once, matching how a human would report "N metres of
    line had a spurious flag") per metre of line covered by this example's
    trace range. `None` if `trace_spacing_m` is not a real, positive value
    -- never a fabricated distance.
    """
    if trace_spacing_m is None or trace_spacing_m <= 0:
        return None
    p, t = pred.astype(bool), truth.astype(bool)
    fp_columns = int(np.any(p & ~t, axis=0).sum())
    length_m = pred.shape[1] * trace_spacing_m
    if length_m <= 0:
        return None
    return fp_columns / length_m


def chance_baseline_precision(truth: np.ndarray) -> Optional[float]:
    """The precision a detector flagging every cell would achieve -- the honest floor a real score must clear."""
    t = truth.astype(bool)
    return float(t.sum() / t.size) if t.size > 0 else None


# ---------------------------------------------------------------------------
# baseline comparison -- scores the EXISTING statistical detector
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExampleScore:
    example_index: int
    site_id: str
    metrics: dict


def score_examples(
    examples: list[GPRTrainingExample],
    predict: Callable[[GPRTrainingExample], np.ndarray],
    threshold: float = 0.5,
) -> list[ExampleScore]:
    """
    Runs any scorer (`predict`: example -> a (n_samples, n_traces) float
    array of scores/probabilities, same shape as `example.signal`) against
    a set of examples and computes every metric above against each
    example's real mask. `predict` is a plain callable so THE SAME
    function scores the existing statistical detector and any candidate
    learned model -- see `baseline_statistical_detector` below for the
    former, so a future comparison is apples-to-apples by construction,
    not by two separately-written scoring paths that could silently drift
    apart.

    Only examples with `label_level` in `TRAINABLE_LABEL_LEVELS` are
    scored -- a Level C/D example has no mask to score against, and
    scoring one would silently manufacture a truth value for it.
    """
    out = []
    for i, ex in enumerate(examples):
        if ex.label_level not in TRAINABLE_LABEL_LEVELS:
            continue
        shape = (len(ex.signal), len(ex.signal[0]) if ex.signal else 0)
        truth = _mask_to_dense(ex.mask, shape)
        scores = predict(ex)
        pred = scores >= threshold
        pr = precision_recall_f1(pred, truth)
        out.append(ExampleScore(i, ex.site_id, {
            "precision": pr.precision, "recall": pr.recall, "f1": pr.f1,
            "dice": dice_coefficient(pred, truth), "iou": iou(pred, truth),
            "pr_auc": pr_auc(scores.ravel(), truth.ravel()),
            "chance_precision": chance_baseline_precision(truth),
            "true_positives": pr.true_positives, "false_positives": pr.false_positives,
            "false_negatives": pr.false_negatives,
        }))
    return out


def baseline_statistical_detector(example: GPRTrainingExample) -> np.ndarray:
    """
    The CURRENT production detector, applied to one example's own RAW
    signal. Replicates `preprocessing.spatial_grid.anomaly_grid_from_traces`'s
    own composition EXACTLY (its own docstring: "bitwise equivalent to
    `preprocess_trace_local_anomaly(process_gpr_traces(records))` -- the
    FULL composition, filters included") -- background_removal -> dewow ->
    apply_gain -> `_local_anomaly_grid` with the SAME `TRACE_ANOMALY_WINDOWS`
    production itself uses, imported not retyped. The one difference from
    calling that public function directly: it discards the ring
    estimator's own unreliable-cell mask, and a fair baseline must not
    score a cell production itself would refuse to score -- so this calls
    `_local_anomaly_grid` one level down to keep that mask, zeroing (never
    flagging) any cell marked unreliable, exactly as the record-level path
    (`preprocess_trace_local_anomaly`) already does.

    `example.signal` is stored (n_samples, n_traces); this detector's own
    convention (`anomaly_grid_from_traces`) takes (n_traces, n_samples) in
    and returns (n_samples, n_traces) out, so the transpose here is
    orientation bookkeeping, not a scientific choice.
    """
    from preprocessing.spatial_grid import TRACE_ANOMALY_WINDOWS, _local_anomaly_grid
    from preprocessing.trace_processing import apply_gain, background_removal, dewow

    traces = np.array(example.signal, dtype=float).T  # (n_traces, n_samples)
    traces = np.asarray(background_removal(traces.tolist()), dtype=float)
    processed = np.array(
        [apply_gain(dewow(t.tolist(), window=15), gain_type="linear", power=1.0)
         for t in traces],
        dtype=float,
    )
    z_grid, unreliable = _local_anomaly_grid(processed.T, **TRACE_ANOMALY_WINDOWS)
    return np.where(unreliable, 0.0, np.abs(z_grid))


def aggregate_metrics(scores: list[ExampleScore]) -> dict:
    """
    Micro-averages each metric across examples (ignoring `None` — an
    undefined Dice/IoU on an empty example is excluded, not treated as 0).
    Reports the number of examples that actually contributed to each
    metric, since with only 4 real examples this count is itself part of
    the honest result.
    """
    if not scores:
        return {"n_examples": 0}
    keys = scores[0].metrics.keys()
    out = {"n_examples": len(scores)}
    for k in keys:
        vals = [s.metrics[k] for s in scores if s.metrics[k] is not None]
        out[k] = {
            "mean": statistics.mean(vals) if vals else None,
            "n": len(vals),
        }
    return out
