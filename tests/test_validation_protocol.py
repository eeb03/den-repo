"""
Validation protocol and evidence-integrity checks (benchmark.validation_protocol).
"""
import copy
import json
from pathlib import Path

import pytest

from benchmark.validation_protocol import (
    Ledger, ProtocolError, check_freezable, evaluate, exposure_label, git_blob_sha1,
    load_protocol, load_protocol_dict, min_area_to_pass, min_detections_to_pass,
    pass_probability, power_table, protocol_digest, rate_upper_bound, recall_lower_bound,
    verify_committed_file,
)

DRAFT = Path("benchmark/protocols/validation-protocol-v1.draft.json")
PLANNED_OK = {"objects": {"linear": 16, "compact": 16}, "verified_empty_area_m2": 20.0}


def draft():
    return json.loads(DRAFT.read_text())


def sealed(doc=None):
    d = copy.deepcopy(doc or draft())
    d["truth_digests"] = {"site-B": "sha256:" + "b" * 64, "site-C": "sha256:" + "c" * 64}
    return d


def frozen(doc=None):
    d = sealed(doc)
    d["status"] = "frozen"
    return d


# --- exact statistics (values checked against the audit tables) --------------

def test_one_sided_clopper_pearson_lower_bounds():
    assert recall_lower_bound(5, 5, 0.05) == pytest.approx(0.549, abs=1e-3)
    assert recall_lower_bound(7, 7, 0.05) == pytest.approx(0.652, abs=1e-3)
    assert recall_lower_bound(14, 16, 0.05) == pytest.approx(0.656, abs=1e-3)
    assert recall_lower_bound(0, 10, 0.05) == 0.0


def test_poisson_upper_bound_and_required_area():
    assert rate_upper_bound(0, 12.0, 0.05) == pytest.approx(2.996 / 12, abs=1e-3)
    assert min_area_to_pass(0, 0.25, 0.05) == pytest.approx(11.98, abs=0.01)
    assert min_area_to_pass(1, 0.25, 0.05) == pytest.approx(18.98, abs=0.01)


def test_minimum_detections_and_power():
    assert min_detections_to_pass(5, 0.6, 0.05) is None
    assert min_detections_to_pass(7, 0.6, 0.05) == 7
    assert min_detections_to_pass(16, 0.6, 0.05) == 14
    assert pass_probability(16, 0.6, 0.05, 0.9) == pytest.approx(0.789, abs=1e-3)
    assert pass_probability(7, 0.6, 0.05, 0.9) == pytest.approx(0.478, abs=1e-3)
    assert pass_probability(5, 0.6, 0.05, 0.99) == 0.0


# --- loading -------------------------------------------------------------------

def test_the_committed_draft_loads_and_is_a_draft():
    p = load_protocol(DRAFT)
    assert p.status == "draft" and p.truth_digests == {}
    assert p.recall["compact"].min_n == 16
    assert [r["id"] for r in p.doc["revisions"]] == ["REV-1", "REV-2", "REV-3", "REV-4"]


def test_unknown_fields_and_bad_statuses_are_refused():
    d = draft()
    d["shortcut"] = True
    with pytest.raises(ProtocolError, match="unknown"):
        load_protocol_dict(d)
    d = draft()
    d["status"] = "final"
    with pytest.raises(ProtocolError, match="status"):
        load_protocol_dict(d)


def test_every_group_needs_a_recall_gate():
    d = draft()
    del d["gates"]["recall"]["compact"]
    with pytest.raises(ProtocolError, match="compact"):
        load_protocol_dict(d)


def test_revisions_and_uncertainties_must_be_recorded():
    d = draft()
    del d["uncertainties"]
    with pytest.raises(ProtocolError, match="uncertainties"):
        load_protocol_dict(d)


# --- freezing ------------------------------------------------------------------

def test_the_draft_is_not_freezable_until_truth_is_sealed():
    reasons = check_freezable(load_protocol(DRAFT), PLANNED_OK)
    assert any("site-B" in r and "not sealed" in r for r in reasons)
    assert check_freezable(load_protocol_dict(sealed()), PLANNED_OK) == []


def test_the_briefs_original_counts_are_refused():
    planned = {"objects": {"linear": 7, "compact": 5}, "verified_empty_area_m2": 12.0}
    reasons = check_freezable(load_protocol_dict(sealed()), planned)
    assert any("compact" in r and "even 5/5" in r for r in reasons)
    assert any("below min_area_m2" in r for r in reasons)


def test_an_unpassable_area_is_refused_even_with_a_low_minimum():
    d = sealed()
    d["gates"]["false_alarms"]["min_area_m2"] = 0
    reasons = check_freezable(load_protocol_dict(d),
                              {"objects": PLANNED_OK["objects"], "verified_empty_area_m2": 8.0})
    assert any("even zero false alarms" in r for r in reasons)


def test_sites_sharing_a_truth_digest_are_not_independent():
    d = sealed()
    d["truth_digests"]["site-C"] = d["truth_digests"]["site-B"]
    assert any("share a truth digest" in r for r in check_freezable(load_protocol_dict(d),
                                                                    PLANNED_OK))


def test_only_a_draft_can_be_frozen():
    assert any("only a draft" in r for r in check_freezable(load_protocol_dict(frozen()),
                                                            PLANNED_OK))


def test_power_table_is_reported():
    t = power_table(load_protocol(DRAFT), ns=(16,), recalls=(0.9,))
    assert t["linear"][16] == {"k_min": 14, "pass_probability": {0.9: 0.789}}


# --- integrity -----------------------------------------------------------------

def test_digest_ignores_formatting_but_not_content():
    d = draft()
    assert protocol_digest(d) == protocol_digest(json.loads(json.dumps(d, indent=7)))
    d2 = copy.deepcopy(d)
    d2["gates"]["recall"]["linear"]["threshold"] = 0.59
    assert protocol_digest(d2) != protocol_digest(d)


def test_git_blob_hash_matches_git(tmp_path):
    # `printf 'hello\n' | git hash-object --stdin`
    assert git_blob_sha1(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"
    f = tmp_path / "freeze.json"
    f.write_bytes(b"hello\n")
    verify_committed_file(f, "ce013625030ba8dba906f756967f9e9ca394464a")
    f.write_bytes(b"hello!\n")
    with pytest.raises(ProtocolError, match="edited"):
        verify_committed_file(f, "ce013625030ba8dba906f756967f9e9ca394464a")


# --- one-shot ledger -----------------------------------------------------------

def test_a_test_site_opens_once_under_the_committed_frozen_digest(tmp_path):
    p = load_protocol_dict(frozen())
    ledger = Ledger(tmp_path / "ledger.jsonl")
    entry = ledger.open_site(p, "site-B", p.digest, "tester", now="2026-10-17T00:00:00+00:00")
    assert entry["truth_digest"] == "sha256:" + "b" * 64
    with pytest.raises(ProtocolError, match="opened once"):
        ledger.open_site(p, "site-B", p.digest, "tester")


def test_the_ledger_refuses_drafts_changed_protocols_and_dev_sites(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    with pytest.raises(ProtocolError, match="frozen protocol"):
        ledger.open_site(load_protocol_dict(sealed()), "site-B", "x", "tester")
    p = load_protocol_dict(frozen())
    with pytest.raises(ProtocolError, match="changed after freezing"):
        ledger.open_site(p, "site-B", "sha256:" + "0" * 64, "tester")
    with pytest.raises(ProtocolError, match="development"):
        ledger.open_site(p, "site-A", p.digest, "tester")
    assert ledger.entries() == []


# --- evaluation ----------------------------------------------------------------

RESULT = {"counts": {"linear": {"n": 16, "detected": 15}, "compact": {"n": 16, "detected": 14}},
          "false_alarms": {"n": 1, "verified_empty_area_m2": 20.0}}


def test_a_ledgered_one_shot_test_can_pass(tmp_path):
    p = load_protocol_dict(frozen())
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.open_site(p, "site-B", p.digest, "tester", now="2026-10-17T00:00:00+00:00")
    r = evaluate(p, "site-B", RESULT, ledger)
    assert r["exposure"].startswith("TEST (one-shot")
    assert r["verdict"] == "PASS"
    assert r["gates"]["false_alarms"]["upper_bound_per_m2"] == pytest.approx(4.744 / 20, abs=1e-3)


def test_one_failed_gate_fails_the_test(tmp_path):
    p = load_protocol_dict(frozen())
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.open_site(p, "site-B", p.digest, "tester")
    bad = copy.deepcopy(RESULT)
    bad["counts"]["compact"]["detected"] = 12
    r = evaluate(p, "site-B", bad, ledger)
    assert r["verdict"] == "FAIL" and not r["gates"]["recall_compact"]["pass"]


def test_unledgered_or_development_results_are_never_validation(tmp_path):
    p = load_protocol_dict(frozen())
    assert evaluate(p, "site-B", RESULT)["verdict"].startswith("NOT A VALIDATION RESULT")
    assert exposure_label(p, "site-A").startswith("DEVELOPMENT")
    assert exposure_label(load_protocol(DRAFT), "site-B").startswith("EXPLORATORY")
    assert exposure_label(p, "elsewhere").startswith("EXPLORATORY")


def test_the_module_imports_no_detector_or_truth():
    import ast
    tree = ast.parse(Path("benchmark/validation_protocol.py").read_text())
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    mods |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not any(m.startswith(("interpretation", "preprocessing", "benchmark")) for m in mods), mods
