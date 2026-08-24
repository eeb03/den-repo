"""
Deterministic tests for `ingestion.four_tu_velocity`: the declared-eps_r ->
velocity resolver, kept separate from the real 4TU corpus so these run
everywhere. Real-corpus tests live in `tests/test_characterise_4tu.py`
(guarded by its existing `REAL` marker), which now exercises the same
functions through `scripts.characterise_4tu`'s thin wrappers.
"""
from __future__ import annotations

import csv

import pytest

from ingestion.four_tu_velocity import (
    C_M_PER_NS,
    DATASET_ID_PREFIX,
    VALIDATION_NOTE,
    declared_permittivity_velocity,
    four_tu_location_id,
    load_metadata,
    normalise_location_id,
    resolve_four_tu_velocity,
)


# --- declared_permittivity_velocity: the physics, never a default ---

def test_eps_9_0_gives_the_documented_reference_velocity():
    v, eps, reason = declared_permittivity_velocity({"Ground relative permittivity": "9.00"})
    assert v == pytest.approx(C_M_PER_NS / 3.0)
    assert eps == pytest.approx(9.0)
    assert reason == "ok"


@pytest.mark.parametrize("eps_r", [8.16, 11.11, 17.36, 19.46])
def test_realistic_4tu_permittivities_produce_the_correct_velocity(eps_r):
    v, eps, reason = declared_permittivity_velocity({"Ground relative permittivity": str(eps_r)})
    assert v == pytest.approx(C_M_PER_NS / (eps_r ** 0.5))
    assert eps == pytest.approx(eps_r)


@pytest.mark.parametrize("row", [None, {}, {"Ground relative permittivity": ""},
                                 {"Ground relative permittivity": "  "}])
def test_missing_permittivity_never_yields_a_fabricated_velocity(row):
    v, eps, reason = declared_permittivity_velocity(row)
    assert v is None and eps is None
    assert "no" in reason or "publishes no" in reason


def test_a_permittivity_below_one_is_rejected_as_non_physical():
    v, eps, reason = declared_permittivity_velocity({"Ground relative permittivity": "0.5"})
    assert v is None and eps is None
    assert "not physical" in reason


def test_a_non_numeric_permittivity_is_rejected():
    v, eps, reason = declared_permittivity_velocity({"Ground relative permittivity": "wet"})
    assert v is None and eps is None
    assert "is not a number" in reason


# --- four_tu_location_id: the ONLY identity signal this module trusts ---

@pytest.mark.parametrize("dataset_id,expected", [
    ("4tu_01.1", "01.1"),
    ("4tu_013.1", "013.1"),
    ("4tu_09.7", "09.7"),
])
def test_the_documented_prefix_convention_yields_the_location_id(dataset_id, expected):
    assert four_tu_location_id(dataset_id) == expected


@pytest.mark.parametrize("dataset_id", [
    "bam_pk266", "tu1208_line1", "", None, "4tu", "4tu_",
])
def test_anything_outside_the_convention_is_not_treated_as_4tu(dataset_id):
    assert four_tu_location_id(dataset_id) is None


# --- resolve_four_tu_velocity: the composable resolution, against a synthetic corpus ---

@pytest.fixture
def synthetic_corpus(tmp_path):
    """A tiny, real-shaped Metadata.csv -- never the real archive, deterministic."""
    path = tmp_path / "Metadata.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(["LocationID", "Ground relative permittivity"])
        writer.writerow(["01.1", "9.00"])
        writer.writerow(["13.1", "11.11"])       # project-13 normalisation target
        writer.writerow(["02.7", "not-a-number"])
        writer.writerow(["02.8", ""])
    return tmp_path


def test_a_dataset_id_outside_the_4tu_convention_resolves_to_nothing(synthetic_corpus):
    assert resolve_four_tu_velocity("bam_pk266", corpus=synthetic_corpus) is None


def test_an_unknown_location_id_resolves_to_nothing(synthetic_corpus):
    assert resolve_four_tu_velocity("4tu_99.9", corpus=synthetic_corpus) is None


def test_an_invalid_declared_permittivity_resolves_to_nothing_not_a_default(synthetic_corpus):
    assert resolve_four_tu_velocity("4tu_02.7", corpus=synthetic_corpus) is None
    assert resolve_four_tu_velocity("4tu_02.8", corpus=synthetic_corpus) is None


def test_a_valid_activity_resolves_to_the_declared_velocity(synthetic_corpus):
    r = resolve_four_tu_velocity("4tu_01.1", corpus=synthetic_corpus)
    assert r is not None
    assert r.location_id == "01.1"
    assert r.eps_r == pytest.approx(9.0)
    assert r.velocity_m_per_ns == pytest.approx(C_M_PER_NS / 3.0)


def test_the_project_13_zero_padding_mismatch_is_resolved_not_left_unmatched(synthetic_corpus):
    """Metadata.csv says '13.1'; a caller may pass the on-disk '013.1' directory name."""
    r = resolve_four_tu_velocity("4tu_013.1", corpus=synthetic_corpus)
    assert r is not None
    assert r.location_id == "13.1"
    assert r.eps_r == pytest.approx(11.11)


def test_resolution_names_where_the_velocity_came_from_and_never_claims_validation(synthetic_corpus):
    r = resolve_four_tu_velocity("4tu_01.1", corpus=synthetic_corpus)
    assert "derived from" in r.velocity_basis
    assert "01.1" in r.velocity_basis        # activity identity is traceable
    assert "declared by" in r.permittivity_basis
    assert "01.1" in r.permittivity_basis
    assert "9.0" in r.permittivity_basis     # the declared quantity itself is preserved
    assert r.validated is False
    assert r.validation_note == VALIDATION_NOTE
    assert "not independently validated" in r.validation_note


def test_normalise_location_id_still_behaves_exactly_as_documented():
    known = {"13.1", "01.1"}
    assert normalise_location_id("013.1", known) == ("13.1", True)
    assert normalise_location_id("01.1", known) == ("01.1", False)
    assert normalise_location_id("99.9", known) == ("99.9", False)


def test_load_metadata_reads_the_real_column_delimiter(synthetic_corpus):
    metadata = load_metadata(synthetic_corpus)
    assert set(metadata) == {"01.1", "13.1", "02.7", "02.8"}
    assert metadata["01.1"]["Ground relative permittivity"] == "9.00"
