"""
Dataset construction tests for Learned Detector V1 (`training.segmentation`).

REAL BAM DATA ONLY -- no synthetic fixture stands in for the ground-truth
extraction itself: these tests exist specifically to pin that
`build_bam_pk266_examples`/`build_bam_pk050_negative_examples` extract
exactly what the real, held archive and its real truth file actually say,
never an invented approximation of it.
"""
from __future__ import annotations

from schemas.segmentation import LabelLevel, LabelSource
from training.segmentation import (
    build_bam_pk050_negative_examples,
    build_bam_pk266_examples,
)


class TestPk266PositiveExamples:
    def test_produces_exactly_the_real_target_count(self):
        """4 real, published targets exist for Pk266 -- never more, never fewer than what associate() actually resolves."""
        examples = build_bam_pk266_examples()
        assert len(examples) == 4

    def test_every_example_is_attributed_to_the_real_specimen(self):
        for ex in build_bam_pk266_examples():
            assert ex.site_id == "Pk266"
            assert ex.dataset_id == "bam-Pk266"

    def test_label_level_and_source_are_never_promoted_beyond_what_was_measured(self):
        for ex in build_bam_pk266_examples():
            assert ex.label_level in (LabelLevel.A_MASK, LabelLevel.B_REGION)
            assert ex.label_source == LabelSource.MEASURED_ASSOCIATION
            assert "confidence" in ex.label_basis

    def test_mask_cells_are_real_picks_not_an_invented_width(self):
        for ex in build_bam_pk266_examples():
            assert ex.mask is not None
            assert ex.mask.n_cells > 0
            assert "no invented width" in ex.mask.rule
            assert ex.mask.n_cells == ex.extra["n_traced_picks"]

    def test_mask_indices_fall_within_the_signal_window(self):
        for ex in build_bam_pk266_examples():
            n_samples, n_traces = len(ex.signal), len(ex.signal[0])
            for t, s in zip(ex.mask.trace_indices, ex.mask.sample_indices):
                assert 0 <= t < n_traces
                assert 0 <= s < n_samples

    def test_signal_is_real_amplitude_not_zeros_or_placeholders(self):
        for ex in build_bam_pk266_examples():
            flat = [v for row in ex.signal for v in row]
            assert any(v != 0.0 for v in flat)

    def test_deterministic_reconstruction(self):
        """Same real archive, same real truth file -> byte-identical examples on a second call."""
        a = build_bam_pk266_examples()
        b = build_bam_pk266_examples()
        assert len(a) == len(b)
        for ea, eb in zip(a, b):
            assert ea.mask.trace_indices == eb.mask.trace_indices
            assert ea.mask.sample_indices == eb.mask.sample_indices
            assert ea.signal == eb.signal

    def test_sample_interval_comes_from_the_real_time_axis(self):
        for ex in build_bam_pk266_examples():
            assert ex.sample_interval_ns is not None
            assert ex.sample_interval_ns > 0

    def test_frequency_is_read_from_the_real_scan_id_not_hardcoded(self):
        examples_26 = build_bam_pk266_examples(scan_id="Pk266_3D_Dataset_2_6_GHz_Rot00")
        examples_15 = build_bam_pk266_examples(scan_id="Pk266_3D_Dataset_1_5_GHz_Rot00")
        assert all(e.antenna_frequency_mhz == 2600.0 for e in examples_26)
        assert all(e.antenna_frequency_mhz == 1500.0 for e in examples_15)


class TestPk050NegativeExample:
    def test_is_a_real_attested_empty_specimen(self):
        examples = build_bam_pk050_negative_examples()
        assert len(examples) == 1
        ex = examples[0]
        assert ex.site_id == "Pk050"
        assert ex.mask is not None
        assert ex.mask.n_cells == 0  # empty mask, not None -- absence is asserted, not missing

    def test_attestation_text_is_carried_verbatim_in_the_label_basis(self):
        ex = build_bam_pk050_negative_examples()[0]
        assert "does not contain any embedded elements" in ex.label_basis

    def test_caveat_about_step_back_walls_is_preserved(self):
        """Pk050 controls for embedded objects, not for 'no reflector at all' -- the caveat must survive into the example."""
        ex = build_bam_pk050_negative_examples()[0]
        assert "step back wall" in ex.label_basis.lower() or "reflector" in ex.label_basis.lower()
