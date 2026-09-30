"""
The time-zero validation corpus (validation/timezero_references.json) and the
arithmetic that compares an automatic pick with it (validation/timezero.py).

What these tests hold in place: an operator's pick is never recorded as
independent evidence; the corpus never carries target truth, depth or
velocity; errors are computed on the raw axis with a stated sign; evidence
types are never pooled; and no uncertainty is produced from evidence that
cannot support one.
"""
import copy
import json
from pathlib import Path

import pytest

from validation.timezero import (
    MANIFEST, ReferenceError_, UNCERTAINTY_NOT_ESTABLISHED, compare, load_manifest,
    load_manifest_dict, method_c_uncertainty, summarise,
)


def raw_manifest():
    return json.loads(Path(MANIFEST).read_text())


def ref(**kw):
    base = {"reference_id": "r1", "dataset": "d", "format": "segy", "path": "x.sgy",
            "reference_ns": 10.0, "uncertainty_ns": 0.3, "evidence_type": "operator_reference",
            "independent": False, "blind": True, "confidence": "high",
            "basis": "flat baseline, sharp departure", "samples_used": "30-35"}
    base.update(kw)
    return base


def manifest(*refs, no_reference=()):
    d = raw_manifest()
    d["references"] = list(refs)
    d["no_reference"] = list(no_reference)
    return d


# --- the corpus ------------------------------------------------------------------

def test_the_held_corpus_loads_and_is_all_operator_picked_and_blind():
    m = load_manifest()
    assert len(m.references) == 20
    assert len(m.no_reference) == 6
    assert {r.evidence_type for r in m.references} == {"operator_reference"}
    assert all(r.blind and not r.independent for r in m.references)


def test_an_operator_pick_can_never_be_declared_independent():
    with pytest.raises(ReferenceError_, match="independent"):
        load_manifest_dict(manifest(ref(independent=True)))


@pytest.mark.parametrize("bad, match", [
    ({"evidence_type": "hunch"}, "evidence_type"),
    ({"uncertainty_ns": 0.0}, "uncertainty"),
    ({"uncertainty_ns": -0.1}, "uncertainty"),
    ({"reference_ns": float("nan")}, "reference_ns"),
    ({"reference_ns": None}, "reference_ns"),
    ({"confidence": "certain"}, "confidence"),
    ({"basis": ""}, "basis"),
])
def test_an_invalid_reference_is_refused(bad, match):
    with pytest.raises(ReferenceError_, match=match):
        load_manifest_dict(manifest(ref(**bad)))


@pytest.mark.parametrize("key", ["target_id", "object_class", "depth_m", "velocity_m_per_ns",
                                 "label", "detector_label"])
def test_object_truth_depth_and_velocity_are_refused_by_name(key):
    with pytest.raises(ReferenceError_, match=key):
        load_manifest_dict(manifest(ref(**{key: 1})))


def test_duplicate_reference_ids_are_refused():
    with pytest.raises(ReferenceError_, match="r1"):
        load_manifest_dict(manifest(ref(), ref()))


def test_a_documented_reference_may_be_independent():
    m = load_manifest_dict(manifest(ref(evidence_type="documented", independent=True)))
    assert m.references[0].independent


# --- errors ------------------------------------------------------------------------

def test_signed_error_is_method_minus_reference_on_the_raw_axis():
    c = compare(load_manifest_dict(manifest(ref(reference_ns=16.6, uncertainty_ns=0.4))).references[0],
                status="derived", pick_ns=17.0, sample_interval_ns=0.2)
    assert c.signed_error_ns == pytest.approx(0.4)
    assert c.abs_error_ns == pytest.approx(0.4)
    assert c.error_samples == pytest.approx(2.0)
    assert c.within_reference_uncertainty is True        # |0.4| <= 0.4


def test_an_inconclusive_pick_has_no_error_and_counts_as_not_derived():
    c = compare(load_manifest_dict(manifest(ref())).references[0],
                status="inconclusive", pick_ns=None, sample_interval_ns=0.2)
    assert c.signed_error_ns is None and c.abs_error_ns is None


def _comparisons(errors, evidence="operator_reference", independent=False):
    out = []
    for i, e in enumerate(errors):
        r = load_manifest_dict(manifest(ref(reference_id=f"r{i}", evidence_type=evidence,
                                            independent=independent))).references[0]
        out.append(compare(r, status="derived" if e is not None else "inconclusive",
                           pick_ns=None if e is None else 10.0 + e, sample_interval_ns=0.1))
    return out


def test_summary_statistics_are_computed_per_evidence_type_never_pooled():
    op = _comparisons([0.5, -0.5, 1.0, None])
    doc = _comparisons([0.1, 0.2], evidence="documented", independent=True)
    s = summarise(op + doc)
    assert set(s) == {"operator_reference", "documented"}
    o = s["operator_reference"]
    assert o["n_references"] == 4 and o["n_derived"] == 3 and o["n_not_derived"] == 1
    assert o["median_abs_error_ns"] == pytest.approx(0.5)
    assert o["mean_abs_error_ns"] == pytest.approx(2.0 / 3)
    assert o["bias_mean_signed_ns"] == pytest.approx(1.0 / 3)
    assert o["derived_rate"] == pytest.approx(0.75)


def test_a_95th_percentile_is_not_reported_from_a_handful_of_errors():
    s = summarise(_comparisons([0.1] * 10))["operator_reference"]
    assert s["p95_abs_error_ns"] is None
    assert "fewer than" in s["p95_note"]
    s = summarise(_comparisons([0.1] * 25))["operator_reference"]
    assert s["p95_abs_error_ns"] == pytest.approx(0.1)


# --- uncertainty is never fabricated ---------------------------------------------

def test_operator_references_alone_never_establish_an_uncertainty():
    u = method_c_uncertainty(_comparisons([0.1] * 50))
    assert u["status"] == UNCERTAINTY_NOT_ESTABLISHED
    assert "independent" in u["reason"]


def test_too_few_independent_references_do_not_establish_one_either():
    u = method_c_uncertainty(_comparisons([0.1, 0.2, 0.3], evidence="documented",
                                          independent=True))
    assert u["status"] == UNCERTAINTY_NOT_ESTABLISHED


# --- the operator view is structurally independent of Method C -------------------

def test_the_operator_view_does_not_import_or_call_method_c():
    import ast
    tree = ast.parse(Path("scripts/timezero_operator_view.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert not any(m.startswith("preprocessing") for m in imported), imported
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
            {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not names & {"direct_wave_consensus_time_zero", "_pick_onset_ns",
                        "resolve_time_zero_for_frame"}


def test_the_corpus_reports_where_a_documented_reference_could_come_from():
    assert any("processed" in r for r in raw_manifest()["category_a_routes_not_held"])
