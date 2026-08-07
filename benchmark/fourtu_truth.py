"""
4TU trial-trench ground truth, at the only resolution the source supports.

WHAT THE SOURCE ACTUALLY PUBLISHES. `Metadata.csv` carries one row per
surveying activity. The field this benchmark rests on is defined verbatim in
`Codebook.pdf` as:

    Amount of utilities -- The number of utilities found. Integer value.

"Found" means found in the **trial trench**. That makes a reported `0` a
positive statement that the trench found nothing, not a blank -- which is why
zero-utility activities can act as negative ground here, and why this module
keeps `attested_zero` separate from `unrecorded`.

WHAT THE SOURCE WITHHOLDS, and what it costs. There are no trench coordinates:
the publishers removed geospatial information from the ground truth to preserve
utility-location confidentiality. So a candidate can never be matched to a
particular utility, and every metric this supports is a per-ACTIVITY count.

THE LIMITATION THAT MATTERS MOST, stated here because it bounds every number
downstream: **a trial trench is a small excavation inside a much larger
surveyed area.** A utility that lies under a survey line but outside the trench
is absent from the truth and present in the ground. A detector response there
is not necessarily wrong. "False positive" therefore cannot mean what it means
on a controlled specimen, and this benchmark does not use the word without
saying so.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

DEFAULT_METADATA = Path(
    "datasets/raw/4tu/96303227-5886-41c9-8607-70fdd2cfe7c1/extracted/Metadata.csv"
)

#: Verbatim from Codebook.pdf, so the definition travels with the data.
COUNT_FIELD = "Amount of utilities"
COUNT_DEFINITION = "The number of utilities found. Integer value."
COUNT_PROVENANCE = "declared_by_source"

TRENCH_SCOPE_CAVEAT = (
    "The count is what the TRIAL TRENCH found, and a trench is a small "
    "excavation inside a much larger surveyed area. A utility under a survey "
    "line but outside the trench is missing from the truth, not from the "
    "ground; a detector response there is not necessarily a false alarm."
)


class FourTuTruthError(RuntimeError):
    pass


@dataclass(frozen=True)
class ActivityTruth:
    location_id: str
    #: None means the field is blank -- unrecorded, NOT zero.
    n_utilities: Optional[int]
    disciplines: tuple[str, ...]
    materials: tuple[str, ...]
    diameters: tuple[str, ...]
    crossing: Optional[bool]
    path_linear: Optional[bool]
    relative_permittivity: Optional[float]
    additional: tuple[str, ...] = ()
    provenance: str = COUNT_PROVENANCE

    @property
    def attested_zero(self) -> bool:
        """The trench was dug and found nothing. Not the same as unrecorded."""
        return self.n_utilities == 0

    @property
    def unrecorded(self) -> bool:
        return self.n_utilities is None

    @property
    def has_utilities(self) -> bool:
        return self.n_utilities is not None and self.n_utilities > 0


@dataclass(frozen=True)
class FourTuTruth:
    activities: dict[str, ActivityTruth]
    source: str
    count_definition: str = COUNT_DEFINITION
    count_provenance: str = COUNT_PROVENANCE
    trench_scope_caveat: str = TRENCH_SCOPE_CAVEAT
    coordinates_available: bool = False
    coordinates_note: str = (
        "withheld by the publisher to preserve utility-location confidentiality; "
        "no candidate can be matched to a particular utility"
    )
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def positives(self) -> list[ActivityTruth]:
        return [a for a in self.activities.values() if a.has_utilities]

    @property
    def attested_zeros(self) -> list[ActivityTruth]:
        return [a for a in self.activities.values() if a.attested_zero]

    @property
    def unrecorded(self) -> list[ActivityTruth]:
        return [a for a in self.activities.values() if a.unrecorded]


def _multi(raw: str) -> tuple[str, ...]:
    """Several fields hold one value per utility, newline-separated."""
    return tuple(v.strip() for v in (raw or "").replace("\r", "\n").split("\n") if v.strip())


def _yes_no(raw: str) -> Optional[bool]:
    v = (raw or "").strip().lower()
    return True if v == "yes" else False if v == "no" else None


def _int_or_none(raw: str) -> Optional[int]:
    v = (raw or "").strip()
    if not v:
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def _float_or_none(raw: str) -> Optional[float]:
    v = (raw or "").strip()
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def normalise_location_id(raw: str) -> str:
    """
    Project 13's directories are named `013.N` while its metadata rows say
    `13.N`. The mismatch is the source's, is one-to-one, and is normalised
    rather than inferred -- recorded here so it is not mistaken for a
    coincidence of naming.
    """
    v = (raw or "").strip()
    if v.startswith("13."):
        return "013." + v.split(".", 1)[1]
    return v


def load_truth(path: Path = DEFAULT_METADATA) -> FourTuTruth:
    if not path.exists():
        raise FourTuTruthError(f"4TU Metadata.csv not present: {path}")

    activities: dict[str, ActivityTruth] = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh, delimiter=";"):
            loc = normalise_location_id(row.get("LocationID", ""))
            if not loc:
                continue
            activities[loc] = ActivityTruth(
                location_id=loc,
                n_utilities=_int_or_none(row.get(COUNT_FIELD, "")),
                disciplines=_multi(row.get("Utility discipline", "")),
                materials=_multi(row.get("Utility material", "")),
                diameters=_multi(row.get("Utility diameter", "")),
                crossing=_yes_no(row.get("Utility crossing", "")),
                path_linear=_yes_no(row.get("Utility path linear", "")),
                relative_permittivity=_float_or_none(row.get("Ground relative permittivity", "")),
                additional=_multi(row.get("Additional utility information", "")),
            )

    if not activities:
        raise FourTuTruthError(f"no activities parsed from {path}")

    return FourTuTruth(
        activities=activities,
        source=str(path),
        notes=(
            "LocationID 13.N normalised to 013.N to match the directory names; "
            "a one-to-one source inconsistency, not an inference.",
        ),
    )
