"""
Yesan is NOT scoring-ready, and the manifest says why.

The manifest now holds the CONSTRUCTED testbed's objects (KEC report
EXTRI-2018-40-534.9607), in the testbed frames. What stays unresolved is which
2021 radar trace is above which of them, so exact matching stays refused in
every frame -- the gate, not a reviewer's memory, is what keeps a guessed
chainage offset out.
"""
import copy
import json

import pytest

from benchmark.predictions import AcquisitionLine, Prediction, PredictionArtifact, TimingProvenance
from benchmark.target_scoring import MatchRule, ScoringBlocked, score
from benchmark.targets import MANIFEST_DIR, Capability, load_manifest, load_manifest_dict

PATH = MANIFEST_DIR / "yesan-fullscale.targets.json"


def test_the_manifest_loads_with_testbed_targets_and_is_not_scoring_ready():
    m = load_manifest(PATH)
    r = m.readiness()
    assert r["status"] == "not_scoring_ready"
    assert m.targets, "the KEC testbed targets are in the manifest"
    assert "detection matching is blocked in every frame" in r["reasons"]
    for frame in ("yesan:testbed-A", "yesan:testbed-B"):
        blocked = r["frames"][frame][Capability.DETECTION_MATCHING.value]
        assert any("yesan-testbed-to-2021-registration" in x for x in blocked)
        assert any("yesan-site-identity" in x for x in blocked)
        assert any("not registered" in x for x in blocked)
    blocked = r["frames"]["yesan:line-A"][Capability.DETECTION_MATCHING.value]
    assert any("yesan-line-registration" in x for x in blocked)
    assert any("yesan-distance-scale" in x for x in blocked)
    assert any("not registered" in x for x in blocked)


def test_adding_a_target_does_not_unlock_matching_while_registration_is_unresolved():
    d = json.loads(PATH.read_text())
    d = copy.deepcopy(d)
    d["depth_reference_surfaces"] = [{"surface_id": "pavement", "description": "road surface"}]
    d["targets"] = [{
        "target_id": "hypothetical-1", "object_class": "unknown",
        "locations": [{"frame_id": "yesan:line-A", "geometry": "point", "coordinates": [45.0]}],
        "evidence": {"basis": "construction_record", "grade": "independently_verified",
                     "independent_of_gpr": True, "source": "hypothetical, for this test only"}}]
    m = load_manifest_dict(d)
    art = PredictionArtifact(
        dataset_id="yesan-fullscale", acquisition_id="DAT_0072_A1", frame_id="yesan:line-A",
        frame_units="m", detector={}, preprocessing={}, input_sha256="x",
        timing=TimingProvenance(), lines=(AcquisitionLine("A", (0.0,), (93.3,)),),
        predictions=(Prediction(prediction_id="p1", line_id="A", position=(45.0,)),))
    with pytest.raises(ScoringBlocked) as exc:
        score(art, m, MatchRule(name="r", radius_kind="fixed", radius=0.5))
    assert "yesan-line-registration" in str(exc.value)
    assert m.readiness()["status"] == "not_scoring_ready"
