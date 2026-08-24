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
REAL GPR ANNOTATION CORPUS V1 -- THE RE-AUDIT (still 4 targets, 1 site)
============================================================================

A second, narrower pass re-asked the SAME question differently: "can any
part of this dataset produce a defensible trace/sample-level annotation",
explicitly including datasets rejected above only for lacking ABSOLUTE
localisation (this pass does not need absolute coordinates, only a real,
defensible relative association). Re-examined, each with a concrete reason
it stays excluded rather than a repeated conclusion:

  TestUM     the PANGAEA archive holds real, precisely-surveyed borehole
             positions but NO independent (non-GPR) measurement of actual
             ice presence -- only the operators' own documented freeze-
             cycle SCHEDULE (intent, not a measurement). Using it as truth
             would validate the GPR against the experiment's own operation,
             the exact circularity this project avoids elsewhere.
  Grimsel    a DIFFERENT real GPR file (`GPR_AU_N-to-S.rd3`, MALA, distinct
             from the geological-model toolkit) is genuinely held, licensed
             In Copyright-NonCommercial (research-only even if usable). Its
             `.rad` header carries the SAME class of untrusted vendor field
             (`SIGNAL POSITION`) this codebase's own time-zero framework
             already refuses to promote, and no coordinate field of any
             kind. Independent shear-zone truth is genuinely strong
             (borehole/OPTV logs, sequence-verified, non-circular) -- but
             the one fact needed to use it (which point of the tunnel path
             the profile's trace 0 corresponds to) is not established in
             anything held, and the one artifact that attempts it
             (`plot_GPR.m`) is a manual, approximate overlay, not a survey
             tie, relative or absolute.
  BAM Pk401  its raw archive was never downloaded at all (only Pk266/Pk050
             are held) -- moot regardless of the drawing-only-position
             problem. Also would not advance SITE independence even if it
             were usable: same fabricator, lab and acquisition system as
             Pk266.

Three ADDITIONAL real datasets, never previously inventoried in any
session, were found and investigated:

  Grimsel AU-tunnel GPR   -- see above (same file, same conclusion).
  Guangzhou University    CC-BY-4.0 (the most permissive of the three), and
  GPR dataset             directories literally named `pipe/`/`rebar/`
  (zenodo 14637589)       suggested real target-type labelling. RULED OUT
                          CONCLUSIVELY: the full central-directory listing
                          (all 5,046 archive members -- fetched via HTTP
                          Range requests against the END of the remote zip,
                          a few MB, not the 3.8 GB archive) contains zero
                          coordinate/target/GPS/truth files of any kind;
                          only `Mark*.txt`/`Nmkr*.txt` operator button-press
                          bookkeeping. `pipe`/`rebar` are category folders,
                          not per-target ground truth.
  Hillside GPR dataset    CC-BY-4.0. Its own PROVENANCE.json claims
  (zenodo 8253179)        "surveyed control points" -- checked directly:
                          all 321 `.cor` coordinate files in the archive
                          are 0 bytes. The claim is unverified/aspirational
                          against what is actually readable; the one
                          remaining unknown (a companion PDF) could not be
                          opened in this environment (no PDF text extractor
                          available) and was not pursued further.

A genuinely NEW external search (not a repeat of the prior broad
localisation search) covered every category the corpus milestone names --
controlled utility test beds, buried-pipe/cable experiments, concrete/rebar
GPR, archaeological/borehole-confirmed targets. Two more real, named
datasets surfaced (a Morocco utilities/voids radargram set, and papers
describing Sense-City/Zhejiang University buried-pipe test beds) and each
was run to ground:

  Morocco utilities/voids  Real bounding-box annotations exist (Level B),
  (Mendeley ww7fd9t325)    but rejected on THREE independent grounds, any
                          one of which would be disqualifying alone: (1)
                          CC BY-NC -- research-only, per this module's own
                          licensing policy; (2) ground truth is OPERATOR
                          VISUAL INTERPRETATION ONLY, no independent
                          excavation/as-built cross-check -- Evidence Grade
                          C, not A/B; (3) only RENDERED JPEG IMAGES are
                          published, no raw trace/sample values at all --
                          structurally incompatible with this module's
                          entire real-amplitude pipeline, which needs
                          physical values, not a lossy picture of them.
  Sense-City (Paris-Est)   A real COST TU1208-affiliated controlled pipe
  / Zhejiang University    test bed, and a real controlled buried-pipeline
                          site -- both described in real journal articles,
                          NEITHER with a discoverable public open-data
                          repository. Not a rejection of the evidence, an
                          absence of a place to get it from; would need
                          direct author contact, a separate, slower,
                          human-reviewed track (the same discipline already
                          used for the 4TU author correspondence), not
                          pursued automatically here.
  TU1208's own             Its unmined `Database_2018/{LIMESTONE,SILT,
  `Database_2018`         GNEISS*,MULTI-LAYER,GPR3_ASCII}` supplement
  (already held)          (found this session, zero-cost to check) is a
                          soil/material dielectric-characterisation
                          database, real ASCII trace data by SOIL TYPE --
                          genuinely useful for a FUTURE velocity milestone,
                          not this one: no target of any kind is named
                          anywhere in it.

CONCLUSION, UNCHANGED BY EITHER PASS: still 4 real, trace-associated
targets, still 1 site (BAM Pk266). Corpus status: STILL BLOCKED, for a
reason that is now exhaustively documented rather than assumed.

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
    PRIMARY_TRAINING_EVIDENCE_GRADES,
    TRAINABLE_LABEL_LEVELS,
    EvidenceGrade,
    GPRTrainingExample,
    LabelLevel,
    LabelSource,
    MaskRegion,
)
from converters.base import MissingDependencyError
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
            # Grade B, not A: the DUCT'S OWN EXISTENCE is about as strong as
            # physical truth gets (a controlled object placed during
            # fabrication) -- but the MASK here also depends on a real
            # ridge-tracked arrival-time MEASUREMENT against a published
            # (not independently re-surveyed) X position, and this grade
            # rates the whole chain a mask rests on, not its strongest link.
            evidence_grade=EvidenceGrade.B_MEASUREMENT_ASSOCIATED,
            label_basis=(
                f"target {target.target_id}: real X footprint from "
                f"benchmark.bam_truth.build_footprint (published X {target.x_mm} mm, "
                f"outer diameter from benchmark/bam_pk266_targets.json, "
                f"transcribed_from_publication), real per-trace arrival time from "
                f"scripts.bam_hyperbola_velocity_audit.associate_target "
                f"(confidence >= its own MIN_PICK_CONFIDENCE threshold). "
                f"Evidence grade B: the duct's existence is a controlled, fabricated "
                f"fact, but the mask rests on a real measurement against a published "
                f"(not independently re-surveyed) position, not full independent X/Y/Z "
                f"validation."
            ),
            sensor_vendor="GSSI",
            antenna_frequency_mhz=2600.0 if "2_6_GHz" in scan_id else 1500.0,
            sample_interval_ns=time_axis.sample_interval_ns,
            preprocessing_version=PREPROCESSING_VERSION,
            license="CC0-1.0",
            commercial_use_permitted=True,
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
        # Grade A: no measurement/association step is involved at all here
        # (unlike the positives) -- the fabricator's own construction
        # record is the direct, authoritative source for "nothing was
        # placed in this specimen", the same standing a controlled
        # negative control has in any other experimental setting.
        evidence_grade=EvidenceGrade.A_INDEPENDENTLY_VERIFIED,
        label_basis=f"{control.attestation} Caveat: {control.caveat}",
        sensor_vendor="GSSI",
        antenna_frequency_mhz=2600.0 if "2_6_GHz" in scan_id else 1500.0,
        sample_interval_ns=time_axis.sample_interval_ns,
        preprocessing_version=PREPROCESSING_VERSION,
        license="CC0-1.0",
        commercial_use_permitted=True,
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



# ---------------------------------------------------------------------------
# corpus infrastructure: portable annotation records, QA, manifest, visual QA
# ---------------------------------------------------------------------------

def annotation_record(example: GPRTrainingExample, annotation_id: str) -> dict:
    """
    The portable, JSON-serializable "Annotation" view of one example --
    Section 17's own sketch, deliberately WITHOUT the (potentially large)
    `signal` array, so a corpus manifest can list thousands of these
    cheaply. This is a VIEW of `GPRTrainingExample`, not a competing
    representation: every field here is read straight off the example,
    nothing is recomputed or reinterpreted.
    """
    return {
        "annotation_id": annotation_id,
        "dataset_id": example.dataset_id,
        "site_id": example.site_id,
        "source_file": example.source_file,
        "target_id": example.extra.get("target_id"),
        "trace_range": list(example.trace_range),
        "sample_range": list(example.sample_range),
        "label": "anomaly_event" if (example.mask and example.mask.n_cells > 0) else "attested_negative",
        "label_level": example.label_level.value,
        "evidence_grade": example.evidence_grade.value if example.evidence_grade else None,
        "label_source": example.label_source.value if example.label_source else None,
        "ground_truth_status": (
            "not_independently_validated"
            if example.evidence_grade != EvidenceGrade.A_INDEPENDENTLY_VERIFIED
            else "independently_validated"
        ),
        "source": example.label_basis,
        "license": example.license,
        "commercial_use_permitted": example.commercial_use_permitted,
        "mask_rule": example.mask.rule if example.mask else None,
        "split": example.split,
    }


@dataclass(frozen=True)
class QAIssue:
    example_index: int
    check: str
    detail: str


def validate_corpus(examples: list[GPRTrainingExample]) -> list[QAIssue]:
    """
    Structural QA over a whole corpus -- collects every issue rather than
    raising on the first, so a caller sees the full picture in one pass.
    An empty return means every check below passed; it does NOT mean the
    corpus is scientifically sufficient (see `assess_split_adequacy` for
    that separate question).
    """
    issues: list[QAIssue] = []
    seen_keys: dict[tuple, int] = {}

    for i, ex in enumerate(examples):
        # 6: site ID present
        if not ex.site_id:
            issues.append(QAIssue(i, "site_id_present", "site_id is empty"))
        # 3/4: trace/sample range valid (start <= end, non-negative)
        if ex.trace_range[0] < 0 or ex.trace_range[1] < ex.trace_range[0]:
            issues.append(QAIssue(i, "trace_range_valid", f"invalid trace_range {ex.trace_range}"))
        if ex.sample_range[0] < 0 or ex.sample_range[1] < ex.sample_range[0]:
            issues.append(QAIssue(i, "sample_range_valid", f"invalid sample_range {ex.sample_range}"))
        # 13: signal dimensions match the declared ranges
        n_samples_expected = ex.sample_range[1] - ex.sample_range[0] + 1
        n_traces_expected = ex.trace_range[1] - ex.trace_range[0] + 1
        if ex.signal:
            actual_samples, actual_traces = len(ex.signal), len(ex.signal[0])
            if (actual_samples, actual_traces) != (n_samples_expected, n_traces_expected):
                issues.append(QAIssue(
                    i, "mask_dimensions_correct",
                    f"signal shape ({actual_samples}, {actual_traces}) does not match "
                    f"declared ranges -> expected ({n_samples_expected}, {n_traces_expected})"))
        # 5: annotation geometry -- mask cells fall within the declared window,
        # and the two parallel arrays are the same length
        if ex.mask is not None:
            if len(ex.mask.trace_indices) != len(ex.mask.sample_indices):
                issues.append(QAIssue(i, "annotation_geometry_valid",
                                      "trace_indices and sample_indices have different lengths"))
            for t, s in zip(ex.mask.trace_indices, ex.mask.sample_indices):
                if not (0 <= t < n_traces_expected) or not (0 <= s < n_samples_expected):
                    issues.append(QAIssue(i, "annotation_geometry_valid",
                                          f"mask cell (trace={t}, sample={s}) falls outside the "
                                          f"example's own window"))
                    break
        # 7/8/9: evidence grade, provenance, label source required for any labelled example
        has_positive_label = ex.mask is not None and ex.mask.n_cells > 0
        if ex.mask is not None:
            if ex.evidence_grade is None:
                issues.append(QAIssue(i, "evidence_grade_present", "labelled example has no evidence_grade"))
            if not ex.label_basis:
                issues.append(QAIssue(i, "provenance_present", "labelled example has no label_basis"))
            if ex.label_source is None:
                issues.append(QAIssue(i, "label_source_present", "labelled example has no label_source"))
        # 14: license metadata present for anything entering the PRIMARY corpus
        if (ex.evidence_grade in PRIMARY_TRAINING_EVIDENCE_GRADES) and not ex.license:
            issues.append(QAIssue(i, "license_present",
                                  "example qualifies for primary training but carries no license"))
        # 11: duplicate detection. NOT keyed on trace_range/sample_range
        # alone: those are WINDOW-LOCAL (re-zeroed per example, as BAM's
        # own per-target construction does), so two genuinely different
        # real targets can legitimately share identical local numbering --
        # confirmed empirically: all 4 real BAM targets independently
        # produced the same (0, 72) window before this fix, which the
        # naive range-only key mistook for 3 duplicates. `target_id` (when
        # a real one exists) or a content fingerprint of the actual signal
        # is what genuinely distinguishes one real example from another.
        if ex.extra.get("target_id") is not None:
            identity = ("target_id", ex.extra["target_id"])
        else:
            flat = tuple(v for row in ex.signal for v in row) if ex.signal else ()
            identity = ("signal_hash", hash(flat))
        key = (ex.dataset_id, ex.site_id, ex.source_file, identity)
        if key in seen_keys:
            issues.append(QAIssue(i, "duplicate_annotation",
                                  f"identical to example {seen_keys[key]}"))
        else:
            seen_keys[key] = i

    # 10: no train/test site overlap, corpus-wide (defense in depth alongside
    # split_by_site's own disjointness check, which this does not call --
    # a corpus may be validated before any split is assigned at all).
    by_split_site: dict[str, set] = {}
    for ex in examples:
        if ex.split:
            by_split_site.setdefault(ex.split, set()).add(ex.site_id)
    splits = list(by_split_site)
    for a in range(len(splits)):
        for b in range(a + 1, len(splits)):
            overlap = by_split_site[splits[a]] & by_split_site[splits[b]]
            if overlap:
                issues.append(QAIssue(-1, "no_train_test_site_overlap",
                                      f"sites {overlap} appear in both {splits[a]!r} and {splits[b]!r}"))

    return issues


def build_corpus_manifest(examples: list[GPRTrainingExample], version: str) -> dict:
    """
    Section 19's versioned manifest -- reproducible FROM the examples
    themselves (every count below is computed, never hand-maintained), so
    the manifest cannot silently drift from the corpus it describes.
    """
    def _count(key_fn) -> dict:
        counts: dict = {}
        for ex in examples:
            k = key_fn(ex)
            if k is not None:
                counts[k] = counts.get(k, 0) + 1
        return counts

    positives = [ex for ex in examples if ex.mask is not None and ex.mask.n_cells > 0]
    negatives = [ex for ex in examples if ex.mask is not None and ex.mask.n_cells == 0]
    unlabelled = [ex for ex in examples if ex.mask is None]

    return {
        "corpus": "Real GPR Annotation Corpus", "version": version,
        "n_examples": len(examples),
        "n_positive": len(positives), "n_negative": len(negatives), "n_unlabelled": len(unlabelled),
        "n_sites": len({ex.site_id for ex in examples}),
        "sites": sorted({ex.site_id for ex in examples}),
        "datasets": sorted({ex.dataset_id for ex in examples}),
        "evidence_grade_distribution": _count(lambda ex: ex.evidence_grade.value if ex.evidence_grade else None),
        "label_level_distribution": _count(lambda ex: ex.label_level.value),
        "vendor_distribution": _count(lambda ex: ex.sensor_vendor),
        "frequency_mhz_distribution": _count(lambda ex: ex.antenna_frequency_mhz),
        "license_distribution": _count(lambda ex: ex.license),
        "qa_issues": len(validate_corpus(examples)),
    }


def render_annotation_overlay(example: GPRTrainingExample, out_path: str) -> str:
    """
    Section 21's visual QA: the real signal, with the real mask cells
    marked, saved as one PNG -- so a human can look at an annotation and
    answer "does this actually correspond to the real GPR response" by
    eye, not just by reading the JSON. NOT decorative: grayscale amplitude
    only, mask cells as plain markers, no invented color scheme implying
    a confidence gradient the data does not have.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as e:
        raise MissingDependencyError(
            "matplotlib is required for training.segmentation.render_annotation_overlay. "
            "Install with: pip install matplotlib"
        ) from e

    arr = np.array(example.signal, dtype=float)
    fig, ax = plt.subplots(figsize=(8, 5))
    vmax = np.percentile(np.abs(arr), 99) or 1.0
    ax.imshow(arr, cmap="gray", vmin=-vmax, vmax=vmax, aspect="auto", interpolation="nearest")
    if example.mask is not None and example.mask.n_cells > 0:
        ax.scatter(example.mask.trace_indices, example.mask.sample_indices,
                   s=6, c="red", marker="o", label=f"annotation ({example.mask.n_cells} cells)")
        ax.legend(loc="upper right", fontsize=8)
    ax.set_xlabel("trace index (window-local)")
    ax.set_ylabel("sample index")
    ax.set_title(f"{example.dataset_id} / {example.source_file} -- {example.label_basis or 'unlabelled'}"[:100])
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


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
