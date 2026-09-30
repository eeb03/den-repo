"""
Time-zero validation corpus and the arithmetic that compares an automatic
pick with it.

A TIMING corpus, not an object benchmark: first-break references on the raw
two-way-time axis, nothing else. It is kept out of `benchmark/` (which holds
buried-target truth) so the two cannot leak into each other, and the loader
refuses target, label, depth and velocity keys by name.

EVIDENCE IS NEVER POOLED. `documented` (the acquisition's own processing or
documentation states the first break) and `independent_measurement` (a
calibration made without the radar data being judged) may be independent of
the estimator; `operator_reference` (a person read it off the raw waveform) is
never independent, even when the picker never saw the estimator's output --
it is one reader's judgement of a feature whose definition is itself fuzzy.
`summarise` reports each evidence type separately.

NO FABRICATED UNCERTAINTY. `method_c_uncertainty` only produces a number from
enough independent/documented references across enough datasets; otherwise it
says `uncertainty not yet established` and why.
"""
from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

MANIFEST = Path(__file__).with_name("timezero_references.json")
SCHEMA = "subterra.timezero_references.v1"

EVIDENCE_TYPES = ("documented", "independent_measurement", "operator_reference")
INDEPENDENT_CAPABLE = ("documented", "independent_measurement")
CONFIDENCES = ("high", "medium", "low")
#: Keys that would turn this corpus into object truth or a depth model.
FORBIDDEN_KEYS = ("target", "object", "label", "depth", "velocity", "detector", "class")

#: A 95th percentile from fewer errors than this is a guess, not a statistic.
MIN_N_FOR_P95 = 20
#: An uncertainty needs at least this many independent references ...
MIN_INDEPENDENT_FOR_UNCERTAINTY = 20
#: ... spread over at least this many datasets.
MIN_DATASETS_FOR_UNCERTAINTY = 3
UNCERTAINTY_NOT_ESTABLISHED = "uncertainty not yet established"


class ReferenceError_(ValueError):
    """A reference that would misstate its evidence."""


@dataclass(frozen=True)
class TimingReference:
    reference_id: str
    dataset: str
    format: str
    path: str
    reference_ns: float
    uncertainty_ns: float
    evidence_type: str
    independent: bool
    blind: bool
    confidence: str
    basis: str
    samples_used: str
    vendor: Optional[str] = None
    antenna_mhz: Optional[float] = None
    load: Optional[dict] = None


@dataclass(frozen=True)
class NoReference:
    path: str
    dataset: str
    format: str
    reason: str
    load: Optional[dict] = None


@dataclass(frozen=True)
class Corpus:
    references: tuple
    no_reference: tuple


def _reference(d: dict) -> TimingReference:
    rid = d.get("reference_id") or "?"
    for key in d:
        if any(bad in key.lower() for bad in FORBIDDEN_KEYS):
            raise ReferenceError_(f"{rid}: key {key!r} is object truth, depth or velocity; "
                                  f"a timing corpus holds first-break times only")
    ev = d.get("evidence_type")
    if ev not in EVIDENCE_TYPES:
        raise ReferenceError_(f"{rid}: evidence_type {ev!r} is not one of {EVIDENCE_TYPES}")
    if d.get("independent") and ev not in INDEPENDENT_CAPABLE:
        raise ReferenceError_(f"{rid}: an {ev} can never be independent -- it is a reading of "
                              f"the same radar data the estimator uses")
    t = d.get("reference_ns")
    if not isinstance(t, (int, float)) or not math.isfinite(t):
        raise ReferenceError_(f"{rid}: reference_ns {t!r} must be a finite number (ns, raw axis)")
    u = d.get("uncertainty_ns")
    if not isinstance(u, (int, float)) or not math.isfinite(u) or u <= 0:
        raise ReferenceError_(f"{rid}: uncertainty {u!r} must be a positive number of ns; "
                              f"no reference is exact")
    if d.get("confidence") not in CONFIDENCES:
        raise ReferenceError_(f"{rid}: confidence {d.get('confidence')!r} not in {CONFIDENCES}")
    if not str(d.get("basis") or "").strip():
        raise ReferenceError_(f"{rid}: basis is required -- what was seen, and where")
    fields = {k: d.get(k) for k in TimingReference.__dataclass_fields__}
    fields["independent"] = bool(d.get("independent"))
    fields["blind"] = bool(d.get("blind"))
    fields["samples_used"] = str(d.get("samples_used") or "")
    return TimingReference(**fields)


def load_manifest_dict(d: dict) -> Corpus:
    if d.get("schema") != SCHEMA:
        raise ReferenceError_(f"schema {d.get('schema')!r}; expected {SCHEMA!r}")
    refs = [_reference(r) for r in d.get("references", [])]
    seen = set()
    for r in refs:
        if r.reference_id in seen:
            raise ReferenceError_(f"duplicate reference_id {r.reference_id!r}")
        seen.add(r.reference_id)
    none = [NoReference(path=n["path"], dataset=n["dataset"], format=n["format"],
                        reason=n["reason"], load=n.get("load"))
            for n in d.get("no_reference", [])]
    return Corpus(tuple(refs), tuple(none))


def load_manifest(path=MANIFEST) -> Corpus:
    return load_manifest_dict(json.loads(Path(path).read_text()))


@dataclass(frozen=True)
class Comparison:
    reference: TimingReference
    status: str
    pick_ns: Optional[float]
    sample_interval_ns: float
    #: pick - reference: positive means the estimator picked LATE.
    signed_error_ns: Optional[float]
    abs_error_ns: Optional[float]
    error_samples: Optional[float]
    within_reference_uncertainty: Optional[bool]

    def as_dict(self) -> dict:
        return {"reference_id": self.reference.reference_id, "dataset": self.reference.dataset,
                "format": self.reference.format, "confidence": self.reference.confidence,
                "evidence_type": self.reference.evidence_type,
                "reference_ns": self.reference.reference_ns,
                "reference_uncertainty_ns": self.reference.uncertainty_ns,
                "status": self.status, "pick_ns": self.pick_ns,
                "signed_error_ns": self.signed_error_ns, "abs_error_ns": self.abs_error_ns,
                "error_samples": self.error_samples,
                "within_reference_uncertainty": self.within_reference_uncertainty}


def compare(reference: TimingReference, status: str, pick_ns: Optional[float],
            sample_interval_ns: float) -> Comparison:
    if pick_ns is None or status != "derived":
        return Comparison(reference, status, pick_ns, sample_interval_ns, None, None, None, None)
    signed = pick_ns - reference.reference_ns
    return Comparison(reference, status, pick_ns, sample_interval_ns, round(signed, 6),
                      round(abs(signed), 6), round(signed / sample_interval_ns, 3),
                      abs(signed) <= reference.uncertainty_ns + 1e-9)


def _percentile(values: list, q: float) -> float:
    """Nearest-rank percentile: no interpolation between observed errors."""
    s = sorted(values)
    return s[max(0, math.ceil(q / 100 * len(s)) - 1)]


def _stats(comparisons: list) -> dict:
    derived = [c for c in comparisons if c.signed_error_ns is not None]
    signed = [c.signed_error_ns for c in derived]
    absolute = [c.abs_error_ns for c in derived]
    samples = [abs(c.error_samples) for c in derived]
    n = len(comparisons)
    out = {
        "n_references": n, "n_derived": len(derived), "n_not_derived": n - len(derived),
        "derived_rate": (len(derived) / n) if n else None,
        "not_derived_by_status": _count(c.status for c in comparisons
                                        if c.signed_error_ns is None),
        "median_abs_error_ns": statistics.median(absolute) if absolute else None,
        "mean_abs_error_ns": statistics.fmean(absolute) if absolute else None,
        "max_abs_error_ns": max(absolute) if absolute else None,
        "median_abs_error_samples": statistics.median(samples) if samples else None,
        "bias_mean_signed_ns": statistics.fmean(signed) if signed else None,
        "bias_median_signed_ns": statistics.median(signed) if signed else None,
        "within_reference_uncertainty": sum(1 for c in derived if c.within_reference_uncertainty),
        "p95_abs_error_ns": None,
        "p95_note": None,
    }
    if len(absolute) >= MIN_N_FOR_P95:
        out["p95_abs_error_ns"] = _percentile(absolute, 95)
    else:
        out["p95_note"] = (f"not estimated: {len(absolute)} errors is fewer than "
                           f"{MIN_N_FOR_P95}, too few for a 95th percentile")
    return out


def _count(items) -> dict:
    out: dict = {}
    for i in items:
        out[i] = out.get(i, 0) + 1
    return out


def summarise(comparisons: list) -> dict:
    """Statistics per evidence type -- never pooled across types."""
    by: dict = {}
    for c in comparisons:
        by.setdefault(c.reference.evidence_type, []).append(c)
    return {ev: _stats(cs) for ev, cs in by.items()}


def method_c_uncertainty(comparisons: list) -> dict:
    """
    An empirical Method C uncertainty, or an explicit refusal. Operator
    references cannot establish one (they are not independent), and neither
    can a handful of independent ones from one or two datasets.
    """
    independent = [c for c in comparisons if c.reference.independent
                   and c.signed_error_ns is not None]
    datasets = {c.reference.dataset for c in independent}
    if len(independent) < MIN_INDEPENDENT_FOR_UNCERTAINTY \
            or len(datasets) < MIN_DATASETS_FOR_UNCERTAINTY:
        return {"status": UNCERTAINTY_NOT_ESTABLISHED,
                "reason": (f"{len(independent)} independent/documented references across "
                           f"{len(datasets)} dataset(s); at least "
                           f"{MIN_INDEPENDENT_FOR_UNCERTAINTY} across "
                           f"{MIN_DATASETS_FOR_UNCERTAINTY} datasets are required. Operator "
                           f"references describe agreement with one reader, not accuracy.")}
    absolute = [c.abs_error_ns for c in independent]
    return {"status": "empirical", "n": len(independent), "datasets": sorted(datasets),
            "p95_abs_error_ns": _percentile(absolute, 95),
            "median_abs_error_ns": statistics.median(absolute)}
