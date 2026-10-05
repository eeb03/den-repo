"""
Known-geometry depth calibration (`schemas.depth_calibration`) and its
`DeclarationKind.DEPTH_CALIBRATION` route.

The fit recovers a known t0 and velocity, refuses every under-determined,
impossible or inconsistent case with the rule that failed, and -- through the
real declarations endpoint -- writes the time zero and velocity as a PAIR:
records corrected, depth rederived, provenance naming the calibration. A
calibration is scientifically sufficient only when redundant, and stops being
so when another declaration splits the pair.
"""
from __future__ import annotations

import math

import pytest

from schemas.depth_calibration import (
    CalibrationError, CalibrationPoint, CalibrationStatus, fit_depth_calibration,
)

V, T0 = 0.12, 1.5


def _pt(depth, time=None, rid=None, source="fabrication_drawing", unc=None, noise=0.0):
    return CalibrationPoint.from_dict(dict(
        depth_m=depth, time_ns=(T0 + 2 * depth / V + noise) if time is None else time,
        depth_source=source, depth_evidence="specimen drawing", reflector_id=rid,
        depth_uncertainty_m=unc))


# --------------------------------------------------------------------------
# the fit
# --------------------------------------------------------------------------

class TestFit:
    def test_recovers_t0_and_velocity_with_redundancy(self):
        pts = [_pt(d, noise=e, rid=f"r{i}") for i, (d, e) in
               enumerate([(0.1, 0.02), (0.2, -0.03), (0.3, 0.01), (0.45, 0.0)])]
        r = fit_depth_calibration(pts, "peak")
        assert r.status is CalibrationStatus.CALIBRATED
        assert r.t0_ns == pytest.approx(T0, abs=0.05)
        assert r.velocity_m_per_ns == pytest.approx(V, rel=0.01)
        assert r.redundant and len(r.leave_one_out) == 4
        assert r.t0_std_ns is not None and r.velocity_std_m_per_ns is not None
        assert r.depth_m(T0 + 2 * 0.25 / V) == pytest.approx(0.25, abs=0.005)

    def test_two_points_fit_but_are_not_redundant(self):
        r = fit_depth_calibration([_pt(0.1), _pt(0.3)], "onset")
        assert r.calibrated and not r.redundant
        assert any("not redundant" in x for x in r.reasons)

    def test_one_point_with_a_fixed_partner_is_not_redundant(self):
        r = fit_depth_calibration([_pt(0.2)], "peak", fixed_velocity_m_per_ns=V)
        assert r.calibrated and r.fixed == "velocity" and not r.redundant
        assert r.t0_ns == pytest.approx(T0, abs=1e-6)
        r = fit_depth_calibration([_pt(0.2)], "peak", fixed_t0_ns=T0)
        assert r.calibrated and r.fixed == "t0"
        assert r.velocity_m_per_ns == pytest.approx(V, rel=1e-6)

    def test_the_pick_convention_is_required_and_recorded(self):
        with pytest.raises(CalibrationError):
            fit_depth_calibration([_pt(0.1), _pt(0.3)], "whenever")
        assert fit_depth_calibration([_pt(0.1), _pt(0.3)], "ONSET").pick_convention == "onset"


class TestRefusals:
    @staticmethod
    def _refused(r, phrase):
        assert r.status is CalibrationStatus.REFUSED
        assert any(phrase in x for x in r.reasons), r.reasons

    def test_one_point_cannot_fit_two_unknowns(self):
        self._refused(fit_depth_calibration([_pt(0.2)], "peak"), "one point cannot")

    def test_reflectors_at_almost_the_same_depth_do_not_determine_velocity(self):
        self._refused(fit_depth_calibration([_pt(0.20), _pt(0.21), _pt(0.22)], "peak"), "span")

    def test_deeper_reflector_picked_earlier_contradicts_the_geometry(self):
        self._refused(fit_depth_calibration([_pt(0.1, time=6.0), _pt(0.3, time=4.0)], "peak"),
                      "contradict")

    def test_an_impossible_velocity_is_refused(self):
        # 0.4 m deeper but only 1 ns later -> v = 0.8 m/ns, faster than light
        self._refused(fit_depth_calibration([_pt(0.1, time=5.0), _pt(0.5, time=6.0)], "peak"),
                      "physically possible")

    def test_inconsistent_picks_are_refused_not_averaged(self):
        pts = [_pt(0.1), _pt(0.2, noise=1.5), _pt(0.3), _pt(0.4)]
        self._refused(fit_depth_calibration(pts, "peak", pick_precision_ns=0.1),
                      "3x the stated pick precision")

    def test_a_reflector_the_others_cannot_predict_fails_leave_one_out(self):
        pts = [_pt(0.1), _pt(0.2), _pt(0.3), _pt(0.4, noise=0.9)]
        self._refused(fit_depth_calibration(pts, "peak", pick_precision_ns=1.0,
                                            loo_tolerance_m=0.02), "leave-one-out")

    def test_fixing_both_partners_is_a_declaration_not_a_calibration(self):
        with pytest.raises(CalibrationError):
            fit_depth_calibration([_pt(0.2)], "peak", fixed_t0_ns=T0, fixed_velocity_m_per_ns=V)

    @pytest.mark.parametrize("source", ["gpr_pick", "radar", "hyperbola_fit", "method_c"])
    def test_a_radar_derived_depth_is_never_calibration_truth(self, source):
        with pytest.raises(CalibrationError, match="radar-derived|not one of"):
            _pt(0.2, source=source)

    @pytest.mark.parametrize("bad", [dict(depth_m=-0.1), dict(depth_m=float("nan")),
                                     dict(depth_evidence=""), dict(time_ns="soon")])
    def test_malformed_points_are_refused(self, bad):
        d = dict(depth_m=0.2, time_ns=5.0, depth_source="core_or_borehole",
                 depth_evidence="core log C3")
        with pytest.raises(CalibrationError):
            CalibrationPoint.from_dict({**d, **bad})


# --------------------------------------------------------------------------
# the provenance model
# --------------------------------------------------------------------------

def test_sufficiency_requires_redundancy_and_an_unbroken_pair():
    from schemas.depth_model import (
        VelocityBasis, time_zero_is_scientifically_sufficient,
        velocity_is_scientifically_sufficient, velocity_model_of,
    )
    from schemas.time_zero import TimeZeroMethod, TimeZeroResult, TimeZeroStatus

    conv = {"velocity_m_per_ns": 0.12, "velocity_basis": "calibrated_from_known_geometry",
            "calibration": {"redundant": True, "time_zero_superseded": False}}
    m = velocity_model_of(conv)
    assert m.basis is VelocityBasis.CALIBRATED_FROM_KNOWN_GEOMETRY
    assert velocity_is_scientifically_sufficient(m)
    for cal in ({"redundant": False}, {"redundant": True, "time_zero_superseded": True}):
        assert not velocity_is_scientifically_sufficient(
            velocity_model_of({**conv, "calibration": cal}))

    def tz(red):
        return TimeZeroResult(status=TimeZeroStatus.CALIBRATED,
                              method=TimeZeroMethod.KNOWN_GEOMETRY_CALIBRATION,
                              correction_ns=1.5, basis="fit", redundant=red)
    assert time_zero_is_scientifically_sufficient(tz(True))
    assert not time_zero_is_scientifically_sufficient(tz(False))


# --------------------------------------------------------------------------
# through the real declarations endpoint
# --------------------------------------------------------------------------

from tests.test_apply_time_zero_route import (  # noqa: E402  (shared fixtures)
    _declare, _stored, _violations, env, own_gpr_dataset, signed_in,
)

assert env  # pytest fixture re-export

FRAME = "d:line1"


def _cal_value(n=4, **kw):
    depths = [0.1, 0.2, 0.3, 0.45][:n]
    return {"pick_convention": "peak", "pick_precision_ns": 0.25, **kw,
            "points": [{"depth_m": d, "time_ns": T0 + 2 * d / V, "depth_source": "core_or_borehole",
                        "depth_evidence": f"core C{i}", "reflector_id": f"core-{i}"}
                       for i, d in enumerate(depths)]}


def _readiness():
    from schemas.depth_model import frame_depth_readiness
    frame, _ = _stored()
    return frame_depth_readiness(frame).as_dict()


def test_a_calibration_writes_the_pair_and_rederives_depth(env):
    Session, root = env
    client = signed_in()
    own_gpr_dataset(client, Session, root)
    _declare(client, "depth_calibration", _cal_value(), frame_id=FRAME)

    frame, records = _stored()
    conv = frame.vertical_axis.conversion
    assert conv["velocity_basis"] == "calibrated_from_known_geometry"
    assert conv["velocity_m_per_ns"] == pytest.approx(V, rel=1e-4)
    assert conv["calibration"]["reflector_ids"] == ["core-0", "core-1", "core-2", "core-3"]
    for r in records[:50]:
        assert r.metadata["corrected_time_ns"] == pytest.approx(
            r.metadata["two_way_time_ns"] - T0, abs=1e-3)
        if r.metadata["corrected_time_ns"] < 0:     # before the calibrated time zero
            assert r.metadata["time_zero_excluded"] and r.depth is None
        else:
            assert r.depth == pytest.approx(r.metadata["corrected_time_ns"] * V / 2, rel=1e-3)
    assert _violations() == []
    ready = _readiness()
    assert ready["time_zero"]["status"] == "calibrated"
    assert ready["time_zero"]["scientifically_sufficient"] is True
    assert ready["velocity"]["scientifically_sufficient"] is True
    # no depth reference is declared on this frame, so it is still not sufficient overall
    assert ready["scientifically_sufficient"] is False


def test_re_running_the_time_zero_hierarchy_keeps_the_calibrated_pair(env):
    Session, root = env
    client = signed_in()
    own_gpr_dataset(client, Session, root)
    _declare(client, "depth_calibration", _cal_value(), frame_id=FRAME)
    resp = client.post("/api/datasets/d/apply_time_zero")
    assert resp.status_code == 200, resp.text
    frame, _ = _stored()
    assert _readiness()["time_zero"]["status"] == "calibrated"   # not replaced by Method C
    assert _violations() == []


def test_a_non_redundant_calibration_is_operational_not_sufficient(env):
    Session, root = env
    client = signed_in()
    own_gpr_dataset(client, Session, root)
    _declare(client, "depth_calibration", _cal_value(n=2), frame_id=FRAME)
    ready = _readiness()
    assert ready["time_zero"]["operationally_available"] is True
    assert ready["time_zero"]["scientifically_sufficient"] is False
    assert ready["velocity"]["scientifically_sufficient"] is False


def test_a_later_time_zero_declaration_unpairs_the_velocity(env):
    Session, root = env
    client = signed_in()
    own_gpr_dataset(client, Session, root)
    _declare(client, "depth_calibration", _cal_value(), frame_id=FRAME)
    _declare(client, "time_zero", {"correction_ns": 2.0, "source": "operator",
                                   "evidence": "first-break pick"}, frame_id=FRAME)
    assert _readiness()["velocity"]["scientifically_sufficient"] is False
    assert _violations() == []


def test_a_later_velocity_declaration_unpairs_the_time_zero(env):
    Session, root = env
    client = signed_in()
    own_gpr_dataset(client, Session, root)
    _declare(client, "depth_calibration", _cal_value(), frame_id=FRAME)
    _declare(client, "depth_conversion", {"velocity_m_per_ns": 0.1, "basis": "handbook"},
             frame_id=FRAME)
    ready = _readiness()
    assert ready["time_zero"]["status"] == "calibrated"
    assert ready["time_zero"]["scientifically_sufficient"] is False
    assert _violations() == []


def test_a_refused_calibration_changes_nothing(env):
    Session, root = env
    client = signed_in()
    own_gpr_dataset(client, Session, root)
    before_frame, before = _stored()
    bad = _cal_value(n=1)                     # one point, nothing fixed
    resp = client.post("/api/spatial/d/declarations",
                       json={"kind": "depth_calibration", "value": bad,
                             "supplied_by": "site engineer", "frame_id": FRAME})
    assert resp.status_code == 422 and "one point cannot" in resp.json()["detail"]
    after_frame, after = _stored()
    assert [r.depth for r in after] == [r.depth for r in before]
    assert after_frame.vertical_axis.conversion == before_frame.vertical_axis.conversion
    assert client.get("/api/spatial/d/declarations").json()["declarations"] == []


def test_a_calibration_must_name_its_line(env):
    Session, root = env
    client = signed_in()
    own_gpr_dataset(client, Session, root)
    resp = client.post("/api/spatial/d/declarations",
                       json={"kind": "depth_calibration", "value": _cal_value(),
                             "supplied_by": "site engineer"})
    assert resp.status_code == 409 and "frame_id" in resp.json()["detail"]
