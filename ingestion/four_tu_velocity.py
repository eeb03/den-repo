"""
Resolves a 4TU utility-survey activity's declared ground relative
permittivity into a GPR propagation velocity.

THE CHAIN THIS PRODUCES, AND NOTHING MORE.

    Metadata.csv "Ground relative permittivity"   DECLARED_BY_SOURCE
        -> v = c / sqrt(eps_r)                     DERIVED
        -> depth = two_way_time_ns * v / 2          DERIVED (already the
                                                      converter's own rule)

This module resolves the first arrow only. The second is
`converters.segy_converter.SEGYConverter`, called with the resulting
`velocity_m_per_ns` exactly as any caller-supplied velocity already is --
see `resolve_four_tu_velocity`'s docstring for the exact call shape. The
third happens automatically: `schemas.provenance.record_provenance` already
classifies any non-None `record.depth` as DERIVED, regardless of where the
velocity came from.

WHY THIS IS ITS OWN MODULE AND NOT A BRANCH IN THE CONVERTER. The SEG-Y
converter is generic: it must not know what 4TU is, or what a "LocationID"
is, or that permittivity is the physical quantity behind a velocity. All of
that dataset-specific knowledge lives here. The converter is given three
plain, generic hooks (`velocity_basis`, `velocity_source_quantity`,
`velocity_source_value`, `velocity_source_basis`) it will happily accept
from any future caller with a declared-quantity velocity, 4TU or otherwise.

WHAT THIS DOES NOT CLAIM. The declared permittivity has no published
measurement method, instrument, or uncertainty (`Codebook.pdf` defines the
field only as "the relative permittivity of the subsurface soil") and the
resulting velocity has never been checked against 4TU's own trench-depth
ground truth: the public archive withholds trench coordinates, and its
`survey_map.png` sketches carry no scale or origin to tie a trench distance
to a trace index (independently verified: real survey-line lengths in one
activity span 5.88-6.32 m while their drawn arrows differ by roughly 3x, so
the sketches do not even preserve real line length proportionally). See
`docs/external-calibration-dataset-audit.md` and
`docs/cross-dataset-evidence-audit.md` section 2.3. `VALIDATION_NOTE` below
is carried on every resolution so a caller can never render this as
validated by omission.

REUSE, NOT DUPLICATION. `scripts/characterise_4tu.py` used to define its own
`CORPUS`, `load_metadata` and `velocity_for`. It now imports all three from
here; this module is the single copy of the physics and the metadata join.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

#: Speed of light in vacuum, m/ns. Matches `scripts/characterise_4tu.py` and
#: `scripts/bam_hyperbola_velocity_audit.py`'s own copies of this constant.
C_M_PER_NS = 0.299792458

CORPUS = Path("datasets/raw/4tu/96303227-5886-41c9-8607-70fdd2cfe7c1/extracted")
METADATA_FILENAME = "Metadata.csv"
PERMITTIVITY_FIELD = "Ground relative permittivity"

#: The `dataset_id` convention `scripts/characterise_4tu.py::main()` already
#: uses (`f"4tu_{loc}"`). Reused here as the ONLY signal this module accepts
#: for "this record is unambiguously a 4TU activity" -- never inferred from a
#: filename, a CRS, or a coordinate range.
DATASET_ID_PREFIX = "4tu_"

#: Carried on every resolution, unconditionally. Not independently validated:
#: 4TU withholds trench coordinates and its survey maps carry no scale or
#: origin (see module docstring). This is a fact about the SOURCE, not a
#: threshold this module could ever clear by better arithmetic.
VALIDATION_NOTE = (
    "not independently validated: the public 4TU archive withholds trench "
    "coordinates, and its survey_map.png sketches carry no scale or origin "
    "(verified: drawn arrow lengths do not track real survey-line lengths), "
    "so no trench-to-radar-line spatial correspondence exists to check this "
    "velocity against. See docs/cross-dataset-evidence-audit.md section 2.3."
)


def normalise_location_id(activity_dir: str, known_ids: set[str]) -> tuple[str, bool]:
    """
    The dataset's own directory names disagree with its LocationIDs for
    project 13 only: directories are '013.N', Metadata.csv says '13.N'. The
    mapping is one-to-one over 6 entries with no other candidate, so it is
    normalised here and reported as a source inconsistency -- not inferred.

    (Moved here verbatim from `scripts/characterise_4tu.py`, which now
    imports it, so activity-identity resolution has one home.)
    """
    if activity_dir in known_ids:
        return activity_dir, False
    stripped = activity_dir.lstrip("0")
    if stripped in known_ids:
        return stripped, True
    return activity_dir, False


def load_metadata(corpus: Path = CORPUS) -> dict[str, dict]:
    """Every activity's raw Metadata.csv row, keyed by LocationID."""
    path = corpus / METADATA_FILENAME
    with open(path, encoding="utf-8-sig") as fh:
        return {r["LocationID"]: r for r in csv.DictReader(fh, delimiter=";")}


def declared_permittivity_velocity(
    meta_row: Optional[dict],
) -> tuple[Optional[float], Optional[float], str]:
    """
    Velocity and its declared basis from one activity's Metadata.csv row.

    Returns (velocity_m_per_ns, eps_r, reason). The first two are None
    TOGETHER on any failure -- a missing, blank, non-numeric, or non-physical
    (eps_r < 1) permittivity -- and `reason` always says which. Never a
    default: this function either returns a real, declared-quantity velocity
    or nothing at all.
    """
    if meta_row is None:
        return None, None, "no Metadata.csv row for this LocationID"
    raw = (meta_row.get(PERMITTIVITY_FIELD) or "").strip()
    if not raw:
        return None, None, "Metadata.csv publishes no relative permittivity for this activity"
    try:
        eps = float(raw)
    except ValueError:
        return None, None, f"relative permittivity {raw!r} is not a number"
    if eps < 1.0:
        return None, None, f"relative permittivity {eps} is below 1, which is not physical"
    return C_M_PER_NS / math.sqrt(eps), eps, "ok"


def four_tu_location_id(dataset_id: str) -> Optional[str]:
    """
    The LocationID implied by `dataset_id`, ONLY under the exact `4tu_<id>`
    convention this repository already uses. Anything else -- no prefix, or
    an empty suffix -- returns None rather than a guess.
    """
    if not dataset_id or not dataset_id.startswith(DATASET_ID_PREFIX):
        return None
    loc = dataset_id[len(DATASET_ID_PREFIX):]
    return loc or None


@dataclass(frozen=True)
class FourTuVelocityResolution:
    """
    Everything needed to attach a 4TU-declared velocity to a SEG-Y frame,
    and to answer the six traceability questions this feature exists to
    answer: which activity, what eps_r, from where, what velocity, which
    formula, and whether it was validated.
    """
    location_id: str
    eps_r: float
    velocity_m_per_ns: float
    #: Passed as `SEGYConverter.load(..., velocity_basis=...)`. Contains
    #: "derived from" so `schemas.provenance.frame_provenance` classifies
    #: the resulting Assumption as ProvenanceClass.DERIVED.
    velocity_basis: str
    #: Passed as `velocity_source_basis`. Contains "declared by" so
    #: `frame_provenance` classifies it as ProvenanceClass.DECLARED_BY_SOURCE.
    permittivity_basis: str
    validated: bool = False
    validation_note: str = VALIDATION_NOTE


def resolve_four_tu_velocity(
    dataset_id: str, corpus: Path = CORPUS,
) -> Optional[FourTuVelocityResolution]:
    """
    Resolves a declared velocity for `dataset_id`, or returns None.

    None means "this is not an unambiguously-identified 4TU activity with a
    usable declared permittivity" -- covering a non-4TU dataset_id, an
    unknown LocationID, and a missing/non-physical permittivity alike. The
    caller is expected to fall back to its own existing default velocity in
    every None case; this function never fabricates one.

    Typical call shape, from ingestion code that already knows a SEG-Y file
    belongs to 4TU activity `dataset_id`:

        resolution = resolve_four_tu_velocity(dataset_id)
        kwargs = {}
        if resolution is not None:
            kwargs = dict(
                velocity_m_per_ns=resolution.velocity_m_per_ns,
                velocity_basis=resolution.velocity_basis,
                velocity_source_quantity="relative permittivity",
                velocity_source_value=resolution.eps_r,
                velocity_source_basis=resolution.permittivity_basis,
            )
        SEGYConverter().load(path, dataset_id=dataset_id, sensor_type=SensorType.GPR,
                              coordinate_encoding="ieee_nmea", **kwargs)

    Omitting `kwargs` entirely (the None case) reproduces today's exact
    default-velocity behaviour -- nothing about a non-4TU or unresolvable
    ingestion call changes.
    """
    location_id = four_tu_location_id(dataset_id)
    if location_id is None:
        return None
    metadata = load_metadata(corpus)
    row = metadata.get(location_id)
    if row is None:
        known = set(metadata)
        normalised, _ = normalise_location_id(location_id, known)
        row = metadata.get(normalised)
        location_id = normalised
    velocity, eps, reason = declared_permittivity_velocity(row)
    if velocity is None:
        return None

    velocity_basis = (
        f"derived from the relative permittivity {eps} published for 4TU activity "
        f"{location_id!r} in Metadata.csv, as c/sqrt(eps_r); {VALIDATION_NOTE}"
    )
    permittivity_basis = (
        f"declared by the 4TU data provider in Metadata.csv (LocationID {location_id!r}, "
        f"field {PERMITTIVITY_FIELD!r} = {eps}); no independently documented measurement "
        f"method or uncertainty is published for this value (Codebook.pdf defines the "
        f"field only as 'the relative permittivity of the subsurface soil')."
    )
    return FourTuVelocityResolution(
        location_id=location_id, eps_r=eps, velocity_m_per_ns=velocity,
        velocity_basis=velocity_basis, permittivity_basis=permittivity_basis,
    )
