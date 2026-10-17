"""
A versioned validation protocol, frozen before any test data are opened, and
the evidence-integrity checks that make "frozen" mean something.

    load_protocol(path) -> Protocol
    check_freezable(protocol, planned) -> list of reasons (empty = freezable)
    evaluate(protocol, site_id, result, ledger) -> gate report

WHY THIS EXISTS. Since PR #13 every experiment has frozen its parameters by
committing a file and checking its git blob hash before the held-out run.
That pattern lived inside each experiment's own script. The controlled
survey (docs/post-pr17-acquisition-strategy-brief.md §6) needs it as shared
infrastructure, plus four things no experiment script had:

  * EXACT GATES with their own feasibility check: a gate that cannot be
    passed with the planned number of objects or verified-empty area is
    refused at freeze, not discovered after the data are spent;
  * SITE ROLES: development, test and holdout sites are disjoint, and each
    test site's truth digest is sealed in the protocol;
  * a ONE-SHOT LEDGER: a test site is opened once, under one frozen
    protocol digest, and a second opening is refused;
  * EXPOSURE LABELS on every result.

Statistics are exact: one-sided Clopper-Pearson lower bounds for recall and
one-sided Poisson upper bounds for false alarms per square metre.

NOTHING HERE READS A DETECTOR OR TRUTH. The gate evaluation reads only the
counts a matching result reports (a plain dict), so this module does not
depend on how matching is implemented.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from scipy.stats import beta, binom, chi2

SCHEMA = "subterra.validation_protocol.v1"
STATUSES = ("draft", "frozen", "superseded")
ROLES = ("development", "test", "holdout")
CLASS_GROUPS = ("linear", "compact")


class ProtocolError(ValueError):
    """A protocol that is malformed, not freezable, or used out of order."""


# ---------------------------------------------------------------------------
# exact statistics
# ---------------------------------------------------------------------------

def recall_lower_bound(k: int, n: int, alpha: float) -> float:
    """One-sided (1 - alpha) Clopper-Pearson lower bound on a proportion."""
    if not (0 <= k <= n) or n <= 0:
        raise ProtocolError(f"invalid count {k}/{n}")
    return 0.0 if k == 0 else float(beta.ppf(alpha, k, n - k + 1))


def rate_upper_bound(c: int, area: float, alpha: float) -> float:
    """One-sided (1 - alpha) exact Poisson upper bound on events per unit area."""
    if c < 0 or area <= 0:
        raise ProtocolError(f"invalid false-alarm count {c} or area {area}")
    return float(chi2.ppf(1 - alpha, 2 * (c + 1)) / 2) / area


def min_detections_to_pass(n: int, threshold: float, alpha: float) -> Optional[int]:
    """Smallest k with lower bound >= threshold, or None if no k out of n passes."""
    for k in range(n + 1):
        if recall_lower_bound(k, n, alpha) >= threshold:
            return k
    return None


def pass_probability(n: int, threshold: float, alpha: float, true_recall: float) -> float:
    k = min_detections_to_pass(n, threshold, alpha)
    return 0.0 if k is None else float(1 - binom.cdf(k - 1, n, true_recall))


def min_area_to_pass(false_alarms: int, max_rate: float, alpha: float) -> float:
    """Verified-empty area needed for the upper bound to reach max_rate."""
    return float(chi2.ppf(1 - alpha, 2 * (false_alarms + 1)) / 2) / max_rate


# ---------------------------------------------------------------------------
# integrity primitives
# ---------------------------------------------------------------------------

def canonical_bytes(doc: dict) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def protocol_digest(doc: dict) -> str:
    """Content digest of a protocol, ignoring key order and whitespace."""
    return "sha256:" + hashlib.sha256(canonical_bytes(doc)).hexdigest()


def git_blob_sha1(data: bytes) -> str:
    """The id git gives these bytes as a blob (`git hash-object`), with no git needed."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def verify_committed_file(path, expected_blob: str) -> bytes:
    """Refuse a file whose bytes are not the committed ones (the PR #13 freeze pattern)."""
    data = Path(path).read_bytes()
    actual = git_blob_sha1(data)
    if actual != expected_blob:
        raise ProtocolError(f"{path}: blob {actual} is not the committed blob {expected_blob}; "
                            f"the frozen file was edited")
    return data


# ---------------------------------------------------------------------------
# the protocol
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RecallGate:
    alpha: float
    threshold: float
    min_n: int


@dataclass(frozen=True)
class FalseAlarmGate:
    alpha: float
    max_rate_per_m2: float
    min_area_m2: float


@dataclass(frozen=True)
class Protocol:
    protocol_id: str
    version: str
    status: str
    sites: dict                  # site_id -> role
    truth_digests: dict          # site_id -> sealed survey-truth digest
    recall: dict                 # class group -> RecallGate
    false_alarms: FalseAlarmGate
    doc: dict
    digest: str

    def sites_with(self, role: str) -> list[str]:
        return sorted(s for s, r in self.sites.items() if r == role)


_DOC_KEYS = {"schema", "protocol_id", "version", "status", "sites", "truth_digests", "gates",
             "matching", "requirements", "runtime", "pooling", "revisions", "uncertainties",
             "references", "$comment"}


def _num(d, key, where, lo=None, hi=None):
    v = d.get(key)
    if not isinstance(v, (int, float)) or not math.isfinite(v) or (lo is not None and v < lo) \
            or (hi is not None and v > hi):
        raise ProtocolError(f"{where}: {key} must be a number in [{lo}, {hi}], got {v!r}")
    return v


def load_protocol_dict(doc: dict) -> Protocol:
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise ProtocolError(f"protocol schema must be {SCHEMA!r}")
    unknown = sorted(set(doc) - _DOC_KEYS)
    if unknown:
        raise ProtocolError(f"unknown protocol field(s) {unknown}; refused rather than ignored")
    for key in ("protocol_id", "version"):
        if not str(doc.get(key) or "").strip():
            raise ProtocolError(f"protocol {key} is required")
    status = doc.get("status")
    if status not in STATUSES:
        raise ProtocolError(f"status {status!r}; one of {STATUSES}")
    sites = doc.get("sites") or {}
    if any(r not in ROLES for r in sites.values()):
        raise ProtocolError(f"site roles must be among {ROLES}")
    gates = doc.get("gates") or {}
    recall = {}
    for g in CLASS_GROUPS:
        r = (gates.get("recall") or {}).get(g)
        if r is None:
            raise ProtocolError(f"a recall gate is required for the {g} group")
        recall[g] = RecallGate(alpha=_num(r, "alpha", f"recall.{g}", 0.0001, 0.5),
                               threshold=_num(r, "threshold", f"recall.{g}", 0, 1),
                               min_n=int(_num(r, "min_n", f"recall.{g}", 1)))
    fa = gates.get("false_alarms") or {}
    fa_gate = FalseAlarmGate(alpha=_num(fa, "alpha", "false_alarms", 0.0001, 0.5),
                             max_rate_per_m2=_num(fa, "max_rate_per_m2", "false_alarms", 0),
                             min_area_m2=_num(fa, "min_area_m2", "false_alarms", 0))
    for key in ("revisions", "uncertainties"):
        if not isinstance(doc.get(key), list):
            raise ProtocolError(f"protocol {key} must be a list (empty only if there are none)")
    return Protocol(protocol_id=doc["protocol_id"], version=doc["version"], status=status,
                    sites=dict(sites), truth_digests=dict(doc.get("truth_digests") or {}),
                    recall=recall, false_alarms=fa_gate, doc=doc, digest=protocol_digest(doc))


def load_protocol(path) -> Protocol:
    return load_protocol_dict(json.loads(Path(path).read_text()))


# ---------------------------------------------------------------------------
# freeze checks
# ---------------------------------------------------------------------------

def check_freezable(p: Protocol, planned: dict) -> list[str]:
    """
    Every reason this protocol cannot be frozen. `planned` gives, for the
    TEST data the gates will be applied to:
        {"objects": {"linear": n, "compact": n}, "verified_empty_area_m2": a}
    A gate that no outcome on the planned data could pass is a reason.
    """
    reasons = []
    if p.status != "draft":
        reasons.append(f"status is {p.status}; only a draft can be frozen")
    if not p.sites_with("development"):
        reasons.append("no development site")
    if not p.sites_with("test"):
        reasons.append("no test site")
    for site in p.sites_with("test") + p.sites_with("holdout"):
        if not str(p.truth_digests.get(site) or "").startswith("sha256:"):
            reasons.append(f"site {site}: its truth digest is not sealed in the protocol")
    digests = [d for d in p.truth_digests.values() if d]
    if len(digests) != len(set(digests)):
        reasons.append("two sites share a truth digest; they are not independent")
    for g, gate in p.recall.items():
        n = int((planned.get("objects") or {}).get(g, 0))
        if n < gate.min_n:
            reasons.append(f"{g}: {n} planned test objects, fewer than min_n {gate.min_n}")
        if min_detections_to_pass(max(n, 1), gate.threshold, gate.alpha) is None:
            reasons.append(f"{g}: with {n} objects even {n}/{n} cannot reach a one-sided "
                           f"{1 - gate.alpha:.0%} lower bound of {gate.threshold}")
    area = float(planned.get("verified_empty_area_m2", 0.0))
    fa = p.false_alarms
    if area < fa.min_area_m2:
        reasons.append(f"verified-empty area {area} m2 is below min_area_m2 {fa.min_area_m2}")
    if area <= 0 or rate_upper_bound(0, area, fa.alpha) > fa.max_rate_per_m2:
        reasons.append(f"verified-empty area {area} m2: even zero false alarms cannot bring the "
                       f"upper bound to {fa.max_rate_per_m2} per m2 "
                       f"(needs {min_area_to_pass(0, fa.max_rate_per_m2, fa.alpha):.1f} m2)")
    return reasons


def power_table(p: Protocol, ns=(6, 8, 10, 12, 16, 20, 24, 30),
                recalls=(0.7, 0.8, 0.9, 0.95)) -> dict:
    """Probability of passing each recall gate, by object count and true recall."""
    return {g: {n: {"k_min": min_detections_to_pass(n, gate.threshold, gate.alpha),
                    "pass_probability": {r: round(pass_probability(n, gate.threshold, gate.alpha,
                                                                   r), 3) for r in recalls}}
                for n in ns}
            for g, gate in p.recall.items()}


# ---------------------------------------------------------------------------
# one-shot ledger
# ---------------------------------------------------------------------------

class Ledger:
    """
    Append-only JSON-lines record of every test-site opening. A test or
    holdout site opens once, under a frozen protocol whose digest matches the
    committed one. Development sites are not ledgered: they may be reused.
    """

    def __init__(self, path):
        self.path = Path(path)

    def entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]

    def open_site(self, p: Protocol, site_id: str, committed_digest: str, opened_by: str,
                  now: Optional[str] = None) -> dict:
        role = p.sites.get(site_id)
        if role is None:
            raise ProtocolError(f"site {site_id} is not in protocol {p.protocol_id}")
        if role == "development":
            raise ProtocolError("development sites are not opened through the ledger")
        if p.status != "frozen":
            raise ProtocolError(f"protocol {p.protocol_id} is {p.status}; a {role} site opens "
                                f"only under a frozen protocol")
        if p.digest != committed_digest:
            raise ProtocolError(f"protocol digest {p.digest} is not the committed "
                                f"{committed_digest}; the protocol changed after freezing")
        previous = [e for e in self.entries() if e["site_id"] == site_id]
        if previous:
            raise ProtocolError(f"site {site_id} was already opened on {previous[0]['opened_utc']} "
                                f"under {previous[0]['protocol_digest']}; a {role} site is "
                                f"opened once")
        entry = {"site_id": site_id, "role": role, "protocol_id": p.protocol_id,
                 "protocol_version": p.version, "protocol_digest": p.digest,
                 "truth_digest": p.truth_digests.get(site_id), "opened_by": opened_by,
                 "opened_utc": now or datetime.now(timezone.utc).isoformat()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
        return entry


# ---------------------------------------------------------------------------
# exposure labels and gate evaluation
# ---------------------------------------------------------------------------

def exposure_label(p: Protocol, site_id: str, ledger: Optional[Ledger] = None) -> str:
    role = p.sites.get(site_id)
    if role is None:
        return "EXPLORATORY (site not in the protocol)"
    if role == "development":
        return "DEVELOPMENT (not independent evidence)"
    if p.status != "frozen":
        return f"EXPLORATORY ({role} site evaluated under a {p.status} protocol)"
    opened = [e for e in (ledger.entries() if ledger else []) if e["site_id"] == site_id]
    if not opened or opened[0]["protocol_digest"] != p.digest:
        return f"EXPLORATORY ({role} site not opened through the ledger under this protocol)"
    return f"{role.upper()} (one-shot, opened {opened[0]['opened_utc']})"


def evaluate(p: Protocol, site_id: str, result: dict, ledger: Optional[Ledger] = None) -> dict:
    """
    Apply the frozen gates to one site's matching counts:
        result["counts"][group] = {"n": .., "detected": ..}
        result["false_alarms"] = {"n": .., "verified_empty_area_m2": ..}
    The verdict is PASS only if every gate passes AND the result is a
    ledgered one-shot test; anything else is reported, never promoted.
    """
    label = exposure_label(p, site_id, ledger)
    gates = {}
    for g, gate in p.recall.items():
        c = (result.get("counts") or {}).get(g) or {}
        n, k = int(c.get("n", 0)), int(c.get("detected", 0))
        lb = recall_lower_bound(k, n, gate.alpha) if n else None
        ok = n >= gate.min_n and lb is not None and lb >= gate.threshold
        gates[f"recall_{g}"] = {"pass": ok, "n": n, "detected": k,
                                "recall": k / n if n else None, "lower_bound": lb,
                                "alpha_one_sided": gate.alpha, "threshold": gate.threshold,
                                "min_n": gate.min_n}
    fa = result.get("false_alarms") or {}
    c, area = int(fa.get("n", 0)), float(fa.get("verified_empty_area_m2", 0.0))
    ub = rate_upper_bound(c, area, p.false_alarms.alpha) if area > 0 else None
    gates["false_alarms"] = {"pass": area >= p.false_alarms.min_area_m2 and ub is not None
                             and ub <= p.false_alarms.max_rate_per_m2,
                             "n": c, "area_m2": area, "upper_bound_per_m2": ub,
                             "max_rate_per_m2": p.false_alarms.max_rate_per_m2,
                             "min_area_m2": p.false_alarms.min_area_m2}
    all_pass = all(v["pass"] for v in gates.values())
    one_shot = label.startswith(("TEST", "HOLDOUT"))
    return {"protocol_id": p.protocol_id, "protocol_version": p.version,
            "protocol_digest": p.digest, "site_id": site_id, "exposure": label, "gates": gates,
            "verdict": ("PASS" if all_pass and one_shot else
                        "FAIL" if one_shot else
                        "NOT A VALIDATION RESULT (" + label + ")"),
            "note": "intersection of all gates; each gate is one-sided at its own alpha"}
