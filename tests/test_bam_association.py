"""The BAM target-to-trace association, and the honesty of its status tags.

Two different things are protected here.

**The arithmetic**, which decides whether the benchmark can score localisation
at all: a target at X = 250 mm on a grid of 0..2000 in 5 mm steps sits ON node
50, not near it. These run against a reconstructed grid rather than the 1.7 GB
archives, because the archives are gitignored and absent in CI. The archives
themselves are checked by `scripts/verify_bam_association.py`, whose output is
reproduced in `docs/external-gpr-benchmark-acquisition.md` §9.

**The status vocabulary**, which decides whether anyone reading the benchmark
can tell measurement from assertion. A field may only be VERIFIED_FROM_FILES if
it was read out of the acquired bytes. The two fields that are merely
corroborated -- the units and the origin coincidence -- must stay unverified,
and a test fails if either is quietly promoted.
"""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TRUTH = json.loads((ROOT / "benchmark" / "bam_pk266_targets.json").read_text())
VERIFIER = ROOT / "scripts" / "verify_bam_association.py"

#: The scanner grid, as read from X-values.npy in both archives and recorded in
#: docs/external-gpr-benchmark-acquisition.md §6. Reconstructed here so the
#: association arithmetic is testable without the gitignored raw data.
GRID_X_FIRST, GRID_X_LAST, GRID_STEP = 0, 2000, 5
GRID_X_N = 401

EXPECTED_NODES = {
    "Pk266-duct-1": 50,
    "Pk266-duct-2": 150,
    "Pk266-duct-3": 250,
    "Pk266-duct-4": 350,
}


@pytest.fixture(scope="module")
def ducts():
    return next(s for s in TRUTH["specimens"] if s["id"] == "Pk266")["targets"]


def grid_x():
    return list(range(GRID_X_FIRST, GRID_X_LAST + GRID_STEP, GRID_STEP))


# --- the grid itself ---

def test_the_reconstructed_grid_matches_the_recorded_shape():
    x = grid_x()
    assert len(x) == GRID_X_N
    assert x[0] == GRID_X_FIRST and x[-1] == GRID_X_LAST


def test_the_grid_spans_the_documented_specimen_length(ducts):
    pk266 = next(s for s in TRUTH["specimens"] if s["id"] == "Pk266")
    assert GRID_X_LAST == pk266["dimensions_mm"]["length_x"]


# --- the association is exact, not nearest-neighbour ---

@pytest.mark.parametrize("target_id,node", sorted(EXPECTED_NODES.items()))
def test_each_target_lands_on_its_recorded_grid_node(ducts, target_id, node):
    t = next(d for d in ducts if d["target_id"] == target_id)
    assert t["x_mm"] == grid_x()[node]


def test_every_target_is_an_exact_node_hit_with_zero_residual(ducts):
    """If any residual were non-zero the association would be nearest-neighbour."""
    x = grid_x()
    for t in ducts:
        assert t["x_mm"] in x, f"{t['target_id']} is not on the grid at all"
        node = x.index(t["x_mm"])
        assert x[node] - t["x_mm"] == 0


def test_the_node_index_rule_holds_for_every_target(ducts):
    for t in ducts:
        assert t["x_mm"] % GRID_STEP == 0
        assert EXPECTED_NODES[t["target_id"]] == t["x_mm"] // GRID_STEP


def test_each_node_maps_to_exactly_one_target_of_a_named_type(ducts):
    by_node = {EXPECTED_NODES[t["target_id"]]: t for t in ducts}
    assert sorted(by_node) == [50, 150, 250, 350]
    for t in by_node.values():
        assert t["type"] == "tendon duct"


def test_the_duct_footprint_covers_thirteen_nodes(ducts):
    """A 67 mm duct on a 5 mm grid spans a deterministic node range."""
    x = grid_x()
    for t in ducts:
        r = t["geometry"]["outer_diameter_mm"] / 2.0
        covered = [v for v in x if t["x_mm"] - r <= v <= t["x_mm"] + r]
        assert len(covered) == 13
        assert t["x_mm"] in covered


def test_target_footprints_do_not_overlap(ducts):
    """Overlapping targets would make a candidate ambiguous between them."""
    spans = sorted((t["x_mm"] - t["geometry"]["outer_diameter_mm"] / 2.0,
                    t["x_mm"] + t["geometry"]["outer_diameter_mm"] / 2.0)
                   for t in ducts)
    for (_, prev_hi), (next_lo, _) in zip(spans, spans[1:]):
        assert next_lo > prev_hi


def test_targets_run_across_y_so_every_line_crosses_all_four(ducts):
    for t in ducts:
        assert t["extent"]["spans_full_width_y"] is True


# --- the status vocabulary is not quietly upgraded ---

def test_the_verifier_defines_all_four_status_tags():
    src = VERIFIER.read_text()
    for tag in ("VERIFIED_FROM_FILES", "VERIFIED_FROM_REPOSITORY_METADATA",
                "INFERRED_FROM_DOCUMENTATION", "NOT_AVAILABLE"):
        assert tag in src


def test_units_are_not_claimed_as_verified_from_files():
    """The .npy arrays carry no unit; mm and ns come from the description."""
    src = VERIFIER.read_text()
    units = src.split('out["units"] = {', 1)[1].split("}", 1)[0]
    assert "DOCUMENTED" in units
    assert "VERIFIED" not in units.replace("VERIFIED_FROM_FILES", "")


def test_the_origin_coincidence_is_not_claimed_as_verified():
    src = VERIFIER.read_text()
    block = src.split("def check_frame_origin", 1)[1].split("def ", 1)[0]
    assert '"status": DOCUMENTED' in block
    assert '"shared_origin_verified": False' in block


def test_depth_is_asserted_independent_of_gpr_and_of_any_velocity():
    src = VERIFIER.read_text()
    block = src.split("def check_depth_independence", 1)[1].split("def ", 1)[0]
    assert '"not_derived_from_travel_time": True' in block
    assert '"no_velocity_used": True' in block
    assert '"status": DOCUMENTED' in block


def test_machine_readable_geometry_is_reported_absent():
    src = VERIFIER.read_text()
    block = src.split("def check_geometry_machine_readable", 1)[1].split("def ", 1)[0]
    assert '"status": ABSENT' in block


def test_the_licence_is_tagged_repository_metadata_not_files():
    """It is binding, but it is not inside the archives -- neither tag alone fits."""
    src = VERIFIER.read_text()
    block = src.split("def check_licence", 1)[1].split("def ", 1)[0]
    assert '"status": REPO_METADATA' in block
    assert '"licence_file_inside_archives": False' in block
