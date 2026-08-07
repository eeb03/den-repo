"""
The unified provenance projection.

What matters here is not that the labels exist, but that they stay HONEST as
data moves through the platform. So the tests are mostly about the transitions:

  - a raw amplitude is measured; after preprocessing the same field is derived;
  - a record with no velocity reports depth UNAVAILABLE, not 0;
  - a GeoTie-registered position is supplied_by_caller, not measured;
  - fusion, which reprojects, must not upgrade a derived coordinate to measured;
  - an object is badged with its WEAKEST class, never its strongest.

`unavailable` is asserted as a real state throughout, because a viewer that
cannot distinguish it from a value is the failure this model prevents.
"""
import pytest

from schemas.provenance import (
    CLASS_STRENGTH, ProvenanceClass, QuantityProvenance, candidate_provenance,
    frame_provenance, record_provenance, summarise,
)
from schemas.spatial import (
    Assumption, AxisKind, CRSKind, CRSProvenance, GeographicPosition, NoPosition,
    OdometryPosition, ProjectedPosition, SpatialRef, VerticalAxis, VerticalDatum,
)
from schemas.subterra_record import SensorType, SubterraRecord
from schemas.survey_frame import SurveyFrame


def _axis(kind=AxisKind.TWO_WAY_TIME_NS, datum=None, conversion=None,
          origin="instrument time-zero at each trace"):
    return VerticalAxis(kind=kind, units="ns", origin=origin, positive_down=True,
                        vertical_datum=datum, conversion=conversion)


def _frame(ref=None, axis=None, assumptions=None):
    return SurveyFrame.model_construct(
        frame_id="ds:line", dataset_id="ds", modality=SensorType.GPR,
        source_format="segy", source_file="line.sgy",
        spatial_ref=ref or SpatialRef(kind=CRSKind.UNKNOWN, name="none"),
        vertical_axis=axis or _axis(), assumptions=assumptions or [],
        source_metadata={})


def _record(**kw):
    base = dict(dataset_id="ds", sensor_type=SensorType.GPR, frame_id="ds:line",
                position=NoPosition(reason="none recorded"), signal=[1.0], metadata={})
    base.update(kw)
    return SubterraRecord(**base)


def _by_quantity(entries):
    return {e.quantity: e for e in entries}


# --- the vocabulary itself ---

def test_a_provenance_statement_must_carry_a_basis():
    with pytest.raises(ValueError):
        QuantityProvenance(quantity="depth", provenance=ProvenanceClass.DERIVED, basis="")


def test_every_class_has_a_strength_and_unavailable_is_weakest():
    assert set(CLASS_STRENGTH) == set(ProvenanceClass)
    assert CLASS_STRENGTH[ProvenanceClass.UNAVAILABLE] == 0
    assert min(CLASS_STRENGTH, key=CLASS_STRENGTH.get) == ProvenanceClass.UNAVAILABLE


# --- frames ---

def test_a_declared_crs_reports_declared_by_source():
    ref = SpatialRef(kind=CRSKind.PROJECTED, code="EPSG:28992",
                     crs_provenance=CRSProvenance.DECLARED_BY_SOURCE,
                     name="stated by the file", horizontal_units="m")
    p = _by_quantity(frame_provenance(_frame(ref=ref)))["horizontal_crs"]
    assert p.provenance == ProvenanceClass.DECLARED_BY_SOURCE
    assert p.value == "EPSG:28992"


def test_an_undeclared_crs_reports_unavailable_rather_than_being_omitted():
    p = _by_quantity(frame_provenance(_frame()))["horizontal_crs"]
    assert p.provenance == ProvenanceClass.UNAVAILABLE


def test_an_inferred_crs_is_not_reported_as_declared():
    """SEGYConverter infers WGS84 from value range; that must not read as declared."""
    ref = SpatialRef(kind=CRSKind.GEOGRAPHIC, code="EPSG:4326",
                     crs_provenance=CRSProvenance.INFERRED,
                     name="inferred from the values' range", horizontal_units="deg")
    p = _by_quantity(frame_provenance(_frame(ref=ref)))["horizontal_crs"]
    assert p.provenance == ProvenanceClass.INFERRED


def test_a_time_axis_is_measured_but_a_depth_axis_is_derived():
    t = _by_quantity(frame_provenance(_frame(axis=_axis())))["vertical_axis"]
    assert t.provenance == ProvenanceClass.MEASURED
    d = _by_quantity(frame_provenance(_frame(
        axis=_axis(kind=AxisKind.DEPTH_M))))["vertical_axis"]
    assert d.provenance == ProvenanceClass.DERIVED


def test_a_missing_vertical_datum_is_reported_as_unavailable():
    p = _by_quantity(frame_provenance(_frame()))["vertical_datum"]
    assert p.provenance == ProvenanceClass.UNAVAILABLE
    assert "cannot be compared" in p.basis


def test_a_caller_supplied_vertical_datum_says_so():
    datum = VerticalDatum(code="NAP", provenance=CRSProvenance.SUPPLIED_BY_CALLER,
                          name="PDOK documentation")
    p = _by_quantity(frame_provenance(_frame(axis=_axis(datum=datum))))["vertical_datum"]
    assert p.provenance == ProvenanceClass.SUPPLIED_BY_CALLER
    assert p.value == "NAP"


def test_absent_depth_conversion_is_a_state_not_a_silence():
    p = _by_quantity(frame_provenance(_frame()))["depth_conversion"]
    assert p.provenance == ProvenanceClass.UNAVAILABLE
    p2 = _by_quantity(frame_provenance(_frame(axis=_axis(conversion={
        "method": "constant_velocity", "formula": "d = t*v/2",
        "velocity_m_per_ns": 0.1}))))["depth_conversion"]
    assert p2.provenance == ProvenanceClass.DERIVED
    assert p2.value == 0.1


@pytest.mark.parametrize("basis,verified,expected", [
    ("MEASURED: wheel-encoder trace spacing", True, ProvenanceClass.MEASURED),
    ("SUPPLIED BY CALLER: velocity 0.1 m/ns", False, ProvenanceClass.SUPPLIED_BY_CALLER),
    ("inferred from the values' range", False, ProvenanceClass.INFERRED),
    ("assumed default soil velocity", False, ProvenanceClass.ASSUMED),
])
def test_frame_assumptions_classify_from_their_own_basis(basis, verified, expected):
    f = _frame(assumptions=[Assumption(key="k", value=1, basis=basis, verified=verified)])
    assert _by_quantity(frame_provenance(f))["assumption:k"].provenance == expected


# --- records, and the transitions ---

def test_a_raw_amplitude_is_measured():
    p = _by_quantity(record_provenance(_record()))["signal"]
    assert p.provenance == ProvenanceClass.MEASURED


def test_preprocessing_downgrades_the_same_field_to_derived():
    r = _record(metadata={"processing_applied": {"dewow": True}})
    assert _by_quantity(record_provenance(r))["signal"].provenance == ProvenanceClass.DERIVED


def test_the_anomaly_z_score_is_derived_and_carries_its_reliability():
    r = _record(metadata={"anomaly_reliable": False})
    p = _by_quantity(record_provenance(r))["signal"]
    assert p.provenance == ProvenanceClass.DERIVED
    assert p.verified is False
    assert "not a physical unit" in p.basis


def test_no_velocity_means_depth_is_unavailable_not_zero():
    p = _by_quantity(record_provenance(_record()))["depth"]
    assert p.provenance == ProvenanceClass.UNAVAILABLE
    assert p.value is None


def test_a_derived_depth_names_the_velocity_and_calls_it_an_assertion():
    r = _record(depth=1.25, metadata={"velocity_m_per_ns": 0.1,
                                      "velocity_source": "supplied_by_caller"})
    p = _by_quantity(record_provenance(r))["depth"]
    assert p.provenance == ProvenanceClass.DERIVED
    assert "not a measurement of it" in p.basis


def test_a_native_position_is_measured():
    r = _record(position=OdometryPosition(along_track_m=1.0, path_id="l"),
                metadata={"position_source": "mala_wheel_odometry"})
    p = _by_quantity(record_provenance(r))["position"]
    assert p.provenance == ProvenanceClass.MEASURED


def test_a_geotie_registered_position_is_supplied_by_caller_not_measured():
    """The whole point of GeoTie being additive: the promotion must stay visible."""
    r = _record(position=OdometryPosition(along_track_m=1.0, path_id="l"),
                registered_position=GeographicPosition(lat=52.0, lon=6.0))
    p = _by_quantity(record_provenance(r))["position"]
    assert p.provenance == ProvenanceClass.SUPPLIED_BY_CALLER
    assert "GeoTie" in p.basis


def test_an_absent_position_reports_its_reason():
    r = _record(position=NoPosition(reason="the headers are (0, 0)"))
    p = _by_quantity(record_provenance(r))["position"]
    assert p.provenance == ProvenanceClass.UNAVAILABLE
    assert "(0, 0)" in p.basis


def test_an_elevation_without_a_declared_datum_is_not_reported_as_measured():
    r = _record(elevation=29.1, metadata={"acquisition_elevation_datum": "UNDECLARED"})
    p = _by_quantity(record_provenance(r))["elevation"]
    assert p.provenance == ProvenanceClass.INFERRED
    assert "declares NO vertical datum" in p.basis


def test_a_record_inherits_its_frames_crs_and_datum_statements():
    ref = SpatialRef(kind=CRSKind.PROJECTED, code="EPSG:28992",
                     crs_provenance=CRSProvenance.DECLARED_BY_SOURCE, name="declared",
                     horizontal_units="m")
    q = _by_quantity(record_provenance(_record(), _frame(ref=ref)))
    assert q["horizontal_crs"].provenance == ProvenanceClass.DECLARED_BY_SOURCE
    assert "vertical_datum" in q


# --- fusion must not launder a derived coordinate ---

def test_reprojection_in_fusion_does_not_upgrade_a_position_to_measured():
    """
    A projected record reprojected at fusion time is still a projected record;
    fusion is read-only, so its provenance must be unchanged afterwards.
    """
    from fusion.sensor_fusion import fuse_datasets
    ref = SpatialRef(kind=CRSKind.PROJECTED, code="EPSG:28992",
                     crs_provenance=CRSProvenance.DECLARED_BY_SOURCE, name="declared",
                     horizontal_units="m")
    frame = _frame(ref=ref)
    r = _record(position=ProjectedPosition(easting=255000.0, northing=473300.0))
    before = _by_quantity(record_provenance(r, frame))["position"].provenance
    fuse_datasets([r], radius_m=10.0, frames=[frame])
    after = _by_quantity(record_provenance(r, frame))["position"].provenance
    assert before == after == ProvenanceClass.MEASURED
    assert r.latitude is None          # fusion did not write a derived coordinate back


# --- summarising for a viewer ---

def test_an_object_is_badged_with_its_weakest_class():
    entries = [
        QuantityProvenance(quantity="a", provenance=ProvenanceClass.MEASURED, basis="x"),
        QuantityProvenance(quantity="b", provenance=ProvenanceClass.ASSUMED, basis="y"),
    ]
    assert summarise(entries)["weakest_class"] == "assumed"


def test_the_summary_lists_what_is_missing_by_name():
    entries = [
        QuantityProvenance(quantity="depth", provenance=ProvenanceClass.UNAVAILABLE, basis="x"),
        QuantityProvenance(quantity="signal", provenance=ProvenanceClass.MEASURED, basis="y"),
    ]
    s = summarise(entries)
    assert s["unavailable"] == ["depth"]
    assert s["counts"] == {"unavailable": 1, "measured": 1}


def test_summarising_nothing_does_not_invent_a_class():
    assert summarise([])["weakest_class"] is None


# --- candidates ---

def _candidate(lateral=None, velocity=None):
    from interpretation.anomaly_candidates import (
        AnomalyCandidate, AnomalyCharacteristics, AnomalyConfidence, AnomalyEvidence,
        AnomalyInterpretation,
    )
    return AnomalyCandidate(
        id="c1", dataset_id="ds",
        evidence=AnomalyEvidence(source_file="l.sgy", trace_range=(1, 5),
                                 depth_range=(0.1, 0.5), n_supporting_cells=9,
                                 peak_value=4.2, peak_trace=3, peak_depth=0.3,
                                 mean_value=3.1),
        characteristics=AnomalyCharacteristics(
            area_cells=9.0, continuity_across_traces=1.0, continuity_across_depth=1.0,
            approx_lateral_extent_m=lateral,
            lateral_extent_source="geographic" if lateral else None,
            approx_depth_extent_m=0.4),
        interpretation=AnomalyInterpretation(anomaly_class="compact", note="n"),
        confidence=AnomalyConfidence(reliable_fraction=1.0, touches_trace_boundary=False,
                                     touches_depth_boundary=False,
                                     velocity_m_per_ns=velocity))


def test_a_candidate_never_claims_ground_truth():
    q = _by_quantity(candidate_provenance(_candidate()))
    assert q["ground_truth"].provenance == ProvenanceClass.UNAVAILABLE
    assert "never a confirmed object" in q["ground_truth"].basis


def test_a_candidates_interpretation_is_labelled_not_an_object_claim():
    q = _by_quantity(candidate_provenance(_candidate()))
    assert "NOT a physical-object claim" in q["interpretation"].basis


def test_an_underivable_lateral_extent_is_unavailable():
    q = _by_quantity(candidate_provenance(_candidate(lateral=None)))
    assert q["lateral_extent_m"].provenance == ProvenanceClass.UNAVAILABLE
    q2 = _by_quantity(candidate_provenance(_candidate(lateral=2.5)))
    assert q2["lateral_extent_m"].provenance == ProvenanceClass.DERIVED


def test_a_candidate_without_a_velocity_has_no_defensible_depth_extent():
    q = _by_quantity(candidate_provenance(_candidate()))
    assert q["depth_extent_m"].provenance == ProvenanceClass.UNAVAILABLE
    q2 = _by_quantity(candidate_provenance(_candidate(velocity=0.1)))
    assert q2["depth_extent_m"].provenance == ProvenanceClass.DERIVED
    assert "an assumption" in q2["depth_extent_m"].basis


def test_every_candidate_entry_is_at_best_derived():
    """Nothing about a detector candidate is measured; it is all computed."""
    for e in candidate_provenance(_candidate(lateral=1.0, velocity=0.1)):
        assert e.provenance != ProvenanceClass.MEASURED


# --- the API surface ---

@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from api.main import app
    return TestClient(app)


def test_the_vocabulary_is_served_so_clients_do_not_hard_code_it(client):
    body = client.get("/api/provenance/vocabulary").json()
    served = {c["value"] for c in body["classes"]}
    assert served == {c.value for c in ProvenanceClass}
    # strongest first, so a client can render in order without sorting
    strengths = [c["strength"] for c in body["classes"]]
    assert strengths == sorted(strengths, reverse=True)
    assert "WEAKEST" in body["note"]


def test_every_served_class_explains_itself(client):
    for c in client.get("/api/provenance/vocabulary").json()["classes"]:
        assert c["meaning"].strip()


def test_an_unknown_dataset_is_a_404_not_an_empty_answer(client):
    assert client.get("/api/provenance/no-such-dataset/frames").status_code == 404
    assert client.get("/api/provenance/no-such-dataset/records").status_code == 404


def test_candidate_provenance_round_trips_through_the_api(client):
    body = client.post("/api/provenance/candidates",
                       json=[_candidate(lateral=2.0, velocity=0.1).model_dump()]).json()
    assert body["count"] == 1
    entry = body["candidates"][0]
    assert entry["id"] == "c1"
    quantities = {e["quantity"] for e in entry["provenance"]}
    assert {"evidence", "interpretation", "ground_truth"} <= quantities
    assert entry["summary"]["weakest_class"] == "unavailable"   # ground_truth


def test_a_malformed_candidate_is_reported_not_silently_dropped(client):
    body = client.post("/api/provenance/candidates",
                       json=[{"id": "bad", "not": "a candidate"}]).json()
    assert body["count"] == 1
    assert "error" in body["candidates"][0]
