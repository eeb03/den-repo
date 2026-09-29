"""
The DRC seeded-field manifests (one per field instance): what they hold, and
why they cannot score yet.

Truth comes from the Demining Research Community's own web-map tables; it was
also transcribed independently from Baur et al. (2023) Table 2 and agrees cell
by cell. The GPR datasets it would be scored against are not public.
"""
import collections

import pytest

from benchmark.predictions import AcquisitionLine, Prediction, PredictionArtifact, TimingProvenance
from benchmark.target_scoring import MatchRule, ScoringBlocked, score
from benchmark.targets import MANIFEST_DIR, Capability, EmptyKind, MeasuredTo, load_manifest

FIELDS = {f: load_manifest(MANIFEST_DIR / f"drc-field{f}.targets.json") for f in (1, 2)}
CONTROL_HOLES = {"F2", "F4", "F6", "F8", "F10", "F12", "F14", "F16"}
BLANKS = {"A14", "A16", "A18", "A20", "A22", "A24", "F18", "F20", "F22", "F24", "F25"}


@pytest.mark.parametrize("field", [1, 2])
def test_every_cell_is_one_of_object_control_hole_or_unresolved_blank(field):
    m = FIELDS[field]
    targets = {t.target_id for t in m.targets}
    holes = {e.location_id for e in m.attested_empty_locations}
    assert len(targets) == 131
    assert holes == CONTROL_HOLES
    assert set(m.truth_source["blank_cells"]) == BLANKS
    assert len(targets | holes | BLANKS) == 150
    assert {e.kind for e in m.attested_empty_locations} == {EmptyKind.CONTROL_HOLE}


@pytest.mark.parametrize("field", [1, 2])
def test_the_independent_transcription_agrees_cell_by_cell(field):
    assert FIELDS[field].truth_source["cross_check"]["mismatches"] == []


def test_items_and_depths_are_the_same_in_both_fields():
    a = {t.target_id: (t.subtype, t.depths[0].value) for t in FIELDS[1].targets}
    b = {t.target_id: (t.subtype, t.depths[0].value) for t in FIELDS[2].targets}
    assert a == b


def test_geometry_is_not_the_same_in_both_fields():
    g1 = FIELDS[1].truth_source["grid_geometry_from_coordinates"]
    g2 = FIELDS[2].truth_source["grid_geometry_from_coordinates"]
    assert abs(g1["row_step_m"] - g2["row_step_m"]) > 0.5
    frames = {m.frames[0].frame_id for m in FIELDS.values()}
    assert frames == {"drc:field1:utm14n", "drc:field2:utm14n"}


def test_ferrous_status_is_carried_as_the_authors_magnet_test():
    t = next(t for t in FIELDS[1].targets if t.target_id == "E19")      # TNT
    assert t.object_class == "TNT"
    assert t.material.startswith("not ferrous by magnet test")


def test_depths_keep_their_unresolved_reference_point():
    for t in FIELDS[1].targets:
        (d,) = t.depths
        assert d.measured_to is MeasuredTo.UNRESOLVED
        assert d.open_question == "drc-depth-point"


@pytest.mark.parametrize("field", [1, 2])
def test_precision_is_gated_and_scoring_refused(field):
    m = FIELDS[field]
    assert m.exhaustive["value"] is False
    assert not m.capability(Capability.FALSE_POSITIVES, m.frames[0].frame_id)[0]
    assert m.readiness()["status"] == "not_scoring_ready"
    art = PredictionArtifact(
        dataset_id=m.dataset_id, acquisition_id="x", frame_id=m.frames[0].frame_id,
        frame_units="m", frame_crs="EPSG:32614", detector={}, preprocessing={},
        input_sha256="x", timing=TimingProvenance(),
        lines=(AcquisitionLine("L", (0.0, 0.0), (10.0, 0.0)),),
        predictions=(Prediction(prediction_id="p", line_id="L", position=(0.0, 0.0)),))
    with pytest.raises(ScoringBlocked) as exc:
        score(art, m, MatchRule(name="r", radius_kind="fixed", radius=0.3, control_radius=0.3))
    assert "drc-gpr-not-public" in str(exc.value)
