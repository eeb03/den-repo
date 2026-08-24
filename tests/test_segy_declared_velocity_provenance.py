"""
Deterministic tests for the SEG-Y converter's generic declared-velocity
hooks (`velocity_basis`, `velocity_source_quantity/value/basis`) and their
projection through `schemas.provenance.frame_provenance`.

These call `SEGYConverter._build_frame` directly with small synthetic
arguments rather than a real SEG-Y file: the hooks live entirely in frame
construction, not in trace/byte parsing, so this is the natural, fast,
deterministic boundary to test them at -- no fixture file required, and
nothing here depends on 4TU or any other real dataset.

The converter itself stays generic: nothing below asserts anything 4TU-
specific about `converters.segy_converter`, only that it accepts and
correctly labels a caller-declared basis. `ingestion.four_tu_velocity` is
what actually supplies 4TU's numbers, and is tested on its own in
`tests/test_four_tu_velocity.py`.
"""
from __future__ import annotations

from pathlib import Path

from converters.segy_converter import DEFAULT_GPR_VELOCITY_M_PER_NS, SEGYConverter
from schemas.provenance import ProvenanceClass, frame_provenance
from schemas.spatial import NoPosition
from schemas.subterra_record import SensorType


def _frame(velocity_m_per_ns, **kwargs):
    return SEGYConverter()._build_frame(
        path=Path("line.sgy"), dataset_id="ds", sensor_type=SensorType.GPR,
        trace_positions=[NoPosition(reason="synthetic")], samples=[0.0, 1.0, 2.0],
        sample_interval=1.0, velocity_m_per_ns=velocity_m_per_ns, trace_count=1,
        **kwargs,
    )


def _assumption(frame, key):
    return next(a for a in frame.assumptions if a.key == key)


def _quantity(frame, name):
    return next(p for p in frame_provenance(frame) if p.quantity == f"assumption:{name}")


class TestGlobalDefaultAndUnrelatedCallersAreUnaffected:
    """The safety constraint this whole feature is built around."""

    def test_the_default_velocity_constant_itself_is_unchanged(self):
        assert DEFAULT_GPR_VELOCITY_M_PER_NS == 0.1

    def test_omitting_every_new_hook_reproduces_the_exact_prior_default_basis(self):
        frame = _frame(DEFAULT_GPR_VELOCITY_M_PER_NS)
        a = _assumption(frame, "gpr_velocity")
        assert a.basis == "assumed default (typical near-surface soil, relative permittivity ~9)"
        assert _quantity(frame, "gpr_velocity").provenance == ProvenanceClass.ASSUMED

    def test_omitting_every_new_hook_with_a_caller_velocity_reproduces_prior_behaviour(self):
        """The BAM/TU1208/any-other-caller path: unchanged unless it opts in."""
        frame = _frame(0.08)
        a = _assumption(frame, "gpr_velocity")
        assert a.basis == "supplied by caller"
        assert _quantity(frame, "gpr_velocity").provenance == ProvenanceClass.SUPPLIED_BY_CALLER
        assert not any(a.key == "gpr_velocity_source_quantity" for a in frame.assumptions)


class TestADeclaredQuantityBasisIsClassifiedDerived:
    def test_a_velocity_basis_containing_derived_from_is_classified_derived(self):
        frame = _frame(0.0999, velocity_basis="derived from the relative permittivity 9.0 ...")
        a = _assumption(frame, "gpr_velocity")
        assert a.value == 0.0999
        assert "derived from" in a.basis
        assert _quantity(frame, "gpr_velocity").provenance == ProvenanceClass.DERIVED

    def test_it_is_never_labelled_assumed(self):
        frame = _frame(0.0999, velocity_basis="derived from the relative permittivity 9.0 ...")
        assert _quantity(frame, "gpr_velocity").provenance != ProvenanceClass.ASSUMED


class TestTheDeclaredSourceQuantityIsPreservedAndClassified:
    def test_the_source_quantity_becomes_its_own_declared_by_source_assumption(self):
        frame = _frame(
            0.0999,
            velocity_basis="derived from the relative permittivity 9.0 for activity '01.1' ...",
            velocity_source_quantity="relative permittivity", velocity_source_value=9.0,
            velocity_source_basis="declared by the 4TU data provider in Metadata.csv "
                                  "(LocationID '01.1', field 'Ground relative permittivity' = 9.0)",
        )
        a = _assumption(frame, "gpr_velocity_source_quantity")
        assert a.value == 9.0
        assert "declared by" in a.basis
        assert "01.1" in a.basis
        assert _quantity(frame, "gpr_velocity_source_quantity").provenance == \
            ProvenanceClass.DECLARED_BY_SOURCE

    def test_no_source_quantity_assumption_appears_when_none_is_supplied(self):
        frame = _frame(0.0999, velocity_basis="derived from something")
        assert not any(a.key == "gpr_velocity_source_quantity" for a in frame.assumptions)

    def test_a_source_quantity_without_an_explicit_basis_still_gets_a_generic_one(self):
        frame = _frame(0.0999, velocity_source_quantity="relative permittivity",
                       velocity_source_value=9.0)
        a = _assumption(frame, "gpr_velocity_source_quantity")
        assert "relative permittivity supplied by caller" in a.basis


class TestNonGprModalityIsUntouched:
    def test_seismic_frames_do_not_gain_a_gpr_velocity_assumption(self):
        frame = SEGYConverter()._build_frame(
            path=Path("line.sgy"), dataset_id="ds", sensor_type=SensorType.SEISMIC,
            trace_positions=[NoPosition(reason="synthetic")], samples=[0.0, 1.0, 2.0],
            sample_interval=1.0, velocity_m_per_ns=0.1, trace_count=1,
            velocity_basis="derived from something", velocity_source_quantity="x",
        )
        assert not any(a.key in ("gpr_velocity", "gpr_velocity_source_quantity")
                       for a in frame.assumptions)
