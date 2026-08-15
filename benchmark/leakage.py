"""
Duplicate evaluation units in a benchmark corpus.

WHY THIS EXISTS. A benchmark score treats its units as independent. If two
units are built from byte-identical measurements they are not independent, and
every statistic computed over them -- a separation AUC, a rank correlation, a
per-unit rate -- is computed over a corpus that is smaller than it claims to
be. Stage 7 found four held INGV datasets sharing a single checksum. That was a
catalogue problem. The same question asked of a benchmark is a correctness
problem, because the answer changes the number that gets reported.

WHAT THIS MODULE DOES AND DOES NOT DECIDE. It finds files that are identical
and reports which units they bind together. It does NOT decide that a corpus is
unusable, and it does not delete anything: a shared file is a fact about the
archive, and the archive is not modified. What it offers is a deterministic
ASSIGNMENT -- each distinct measurement counted for exactly one unit -- so that
a score can be recomputed with every measurement counted once and the two
numbers compared.

WHY THE ASSIGNMENT IS BY SORT ORDER. When N units share a file, some unit must
keep it and the rest must lose it. Any rule is arbitrary; a rule that depends on
the DATA would let the choice be made to improve the score. Sorting the unit
ids is arbitrary in a way that cannot be steered, and it is reproducible, which
is the property that matters. `deduplicate` records the owner of every shared
checksum so the choice is inspectable rather than implicit.

THIS FINDS EXACT DUPLICATES ONLY. Two acquisitions of the same trench on the
same day are near-duplicates that no checksum will catch. Absence of a
duplicate group here is not evidence that units are independent -- it is
evidence that they are not identical, which is a weaker claim.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DuplicateGroup:
    """One set of byte-identical files, and the units they belong to."""
    checksum: str
    #: (unit_id, filename), sorted, one entry per PATH -- a file duplicated
    #: twice inside one unit appears twice.
    members: tuple[tuple[str, str], ...]

    @property
    def units(self) -> tuple[str, ...]:
        return tuple(sorted({unit for unit, _ in self.members}))

    @property
    def spans_units(self) -> bool:
        """The case that damages a benchmark. Within one unit it is redundancy."""
        return len(self.units) > 1

    @property
    def owner(self) -> str:
        """The unit that keeps this measurement under `deduplicate`."""
        return self.units[0]


@dataclass(frozen=True)
class UnitLeakage:
    """How much of one unit's data it does not exclusively own."""
    unit_id: str
    n_files: int
    n_shared: int
    shares_with: tuple[str, ...]

    @property
    def fully_duplicated(self) -> bool:
        """Every file also belongs to another unit: this unit adds no measurement."""
        return self.n_files > 0 and self.n_shared == self.n_files

    @property
    def shared_fraction(self) -> float:
        return self.n_shared / self.n_files if self.n_files else 0.0


@dataclass(frozen=True)
class LeakageReport:
    n_files: int
    n_unique_checksums: int
    groups: tuple[DuplicateGroup, ...]
    units: tuple[UnitLeakage, ...] = field(default_factory=tuple)

    @property
    def cross_unit_groups(self) -> tuple[DuplicateGroup, ...]:
        return tuple(g for g in self.groups if g.spans_units)

    @property
    def affected_units(self) -> tuple[UnitLeakage, ...]:
        return tuple(u for u in self.units if u.n_shared)

    @property
    def fully_duplicated_units(self) -> tuple[UnitLeakage, ...]:
        return tuple(u for u in self.units if u.fully_duplicated)

    @property
    def clean(self) -> bool:
        return not self.cross_unit_groups

    def owner_of(self) -> dict[str, str]:
        """checksum -> the single unit that keeps it."""
        return {g.checksum: g.owner for g in self.groups}

    def as_dict(self) -> dict:
        return {
            "n_files": self.n_files,
            "n_unique_checksums": self.n_unique_checksums,
            "n_duplicate_groups": len(self.groups),
            "n_cross_unit_groups": len(self.cross_unit_groups),
            "clean": self.clean,
            "detects": "exact byte-identical files only; near-duplicates are not detectable this way",
            "assignment_rule": (
                "each shared checksum is owned by the first of its units in sort "
                "order -- arbitrary, but independent of the data and reproducible"
            ),
            "cross_unit_groups": [
                {"checksum": g.checksum, "units": list(g.units), "owner": g.owner,
                 "files": [{"unit": u, "file": f} for u, f in g.members]}
                for g in self.cross_unit_groups
            ],
            "affected_units": [
                {"unit": u.unit_id, "n_files": u.n_files, "n_shared": u.n_shared,
                 "shared_fraction": u.shared_fraction,
                 "fully_duplicated": u.fully_duplicated,
                 "shares_with": list(u.shares_with)}
                for u in self.affected_units
            ],
            "fully_duplicated_units": [u.unit_id for u in self.fully_duplicated_units],
        }


def find_duplicates(files: dict[str, dict[str, str]]) -> LeakageReport:
    """
    `files` maps unit_id -> {filename: checksum}.

    Checksums are supplied rather than computed here so that this stays a pure
    function over a manifest: the same manifest must always produce the same
    report, and hashing a 1.3 GB corpus is not something a test should do.
    """
    by_checksum: dict[str, list[tuple[str, str]]] = {}
    for unit_id in sorted(files):
        for filename in sorted(files[unit_id]):
            by_checksum.setdefault(files[unit_id][filename], []).append((unit_id, filename))

    groups = tuple(
        DuplicateGroup(checksum=checksum, members=tuple(members))
        for checksum, members in sorted(by_checksum.items())
        if len(members) > 1
    )

    shared: dict[str, set[str]] = {}
    counts: dict[str, int] = {}
    for group in groups:
        if not group.spans_units:
            continue
        for unit_id, _ in group.members:
            counts[unit_id] = counts.get(unit_id, 0) + 1
            shared.setdefault(unit_id, set()).update(u for u in group.units if u != unit_id)

    units = tuple(
        UnitLeakage(unit_id=unit_id, n_files=len(files[unit_id]),
                    n_shared=counts.get(unit_id, 0),
                    shares_with=tuple(sorted(shared.get(unit_id, ()))))
        for unit_id in sorted(files)
    )

    n_files = sum(len(v) for v in files.values())
    return LeakageReport(n_files=n_files, n_unique_checksums=len(by_checksum),
                         groups=groups, units=units)


def retained_files(files: dict[str, dict[str, str]],
                   report: LeakageReport) -> dict[str, tuple[str, ...]]:
    """
    The files each unit keeps once every measurement is counted exactly once.

    A unit that owns none of its files retains nothing and drops out of the
    de-duplicated corpus entirely -- which is the honest outcome, because it
    contributed no measurement that another unit did not already contribute.
    """
    owner = report.owner_of()
    out: dict[str, tuple[str, ...]] = {}
    for unit_id in sorted(files):
        kept = tuple(
            filename
            for filename, checksum in sorted(files[unit_id].items())
            if owner.get(checksum, unit_id) == unit_id
        )
        out[unit_id] = kept
    return out
