"""
Volume reconstruction: a gridded GPR acquisition -> a `VolumeProduct`.

EXPLICIT STAGES, each recorded on the product (`processing`, `migration`,
`interpolation`):

  A. acquisition normalisation  the stored array in (trace, line, time) order,
                                exactly as registered; missing lines stay empty
  B. signal preprocessing       dewow and (optional) line-mean background
                                removal -- recorded, never silent; no gain
                                (display gain is a viewer setting)
  C. depth / time axis          DEPTH only with a scientifically sufficient
                                depth model (time zero + velocity + surface
                                reference); otherwise TWO-WAY TIME, labelled
                                as time and never as depth
  D. migration (optional)       Stolt F-K, constant velocity from the frame's
                                active depth model -- never estimated here
  E. grid formation             output lines at measured positions or between
                                them, with a support class, a distance and a
                                count per voxel column; nothing is filled
                                beyond the stated maximum gap
  F. derived display field      envelope (|Hilbert| along z) as a separate
                                field; display window/level is never written
                                into the scientific values

REFUSALS (preview reports them; build raises `VolumeRefused`):
  * no gridded acquisition (line identities / spacings undeclared)
  * fewer than two measured lines: a single line is a B-scan, not a volume
  * a non-metric horizontal axis unit
  * DEPTH requested without a scientifically sufficient depth model
  * migration without a depth-domain volume, or over a grid with missing lines
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.signal import hilbert

from schemas.volume import (
    SUPPORT_CLASS_MEANING, CoordinateFrameKind, HorizontalRegistration, InterpolationSpec,
    MigrationSpec, ProcessingStep, PropertyField, SupportClass, VolumeAxis, VolumeConfig,
    VolumeCoordinateFrame, VolumeProduct, ZDomain,
)

RECONSTRUCTION_VERSION = "subterra-volume-v1@1"
DEWOW_NS = 2.0
MIGRATIONS = ("none", "stolt_fk_3d")
INTERPOLATIONS = ("nearest_no_fill", "linear_bounded")
#: An output line within this fraction of the native spacing of a measured
#: line IS that line.
AT_LINE_TOLERANCE = 0.1
#: Hard ceiling on the voxel count a single build may produce (memory guard).
MAX_VOXELS = 200_000_000


class VolumeRefused(ValueError):
    def __init__(self, reasons: list[str]):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def _h(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------
class Inputs:
    """Everything the build reads, resolved once, with refusals collected."""

    def __init__(self, dataset_id: str, config: VolumeConfig):
        from database.frames_store import load_frames
        from database.grid_store import load_grids
        from schemas.depth_model import frame_depth_readiness, frame_time_zero, velocity_model_of

        self.dataset_id = dataset_id
        self.config = config
        self.refusals: list[str] = []
        self.notes: list[str] = []
        grids = load_grids(dataset_id)
        if config.frame_id:
            grids = [g for g in grids if g.frame_id == config.frame_id]
        self.grid = grids[0] if grids else None
        self.frame = None
        if self.grid is None:
            self.refusals.append(
                "no gridded acquisition is registered for this dataset: a metric volume needs "
                "declared line identities, line order, trace spacing and line spacing; "
                "individual lines without a declared grid stay 2D B-scans")
            return
        frames = {f.frame_id: f for f in load_frames(dataset_id)}
        self.frame = frames.get(self.grid.frame_id)
        if self.frame is None:
            self.refusals.append(f"the grid's frame {self.grid.frame_id!r} is missing")
            return
        g = self.grid
        measured = [j for j in range(g.line_axis.n) if j not in set(g.missing_lines)]
        self.measured_lines = measured
        if len(measured) < 2:
            self.refusals.append(
                f"{len(measured)} measured line(s): a single radar line is a 2D B-scan and is "
                "never extruded into a 3D volume")
        for ax in (g.trace_axis, g.line_axis):
            if ax.metres_per_unit() is None:
                self.refusals.append(f"{ax.name} axis unit {ax.unit!r} is not a length unit "
                                     "this build can convert to metres")
        self.readiness = frame_depth_readiness(self.frame).as_dict()
        self.velocity = velocity_model_of(self.frame.vertical_axis.conversion)
        self.time_zero = frame_time_zero(self.frame)
        self.depth_ok = bool(self.readiness.get("scientifically_sufficient"))

        want = config.z_domain
        if want not in ("auto", "depth", "time"):
            self.refusals.append(f"z_domain must be auto, depth or time, not {want!r}")
            want = "time"
        if want == "depth" and not self.depth_ok:
            self.refusals.append(
                "a depth volume needs a scientifically sufficient depth model (time zero, "
                "velocity and surface reference); this frame's: "
                + "; ".join(self.readiness.get("reasons") or ["not sufficient"])
                + ". A time-domain volume (two-way time, ns) is available instead.")
        self.z_domain = ZDomain.DEPTH if (want in ("auto", "depth") and self.depth_ok) else ZDomain.TWO_WAY_TIME
        if want == "auto" and not self.depth_ok:
            self.notes.append("depth model not scientifically sufficient: z is two-way travel "
                              "time (ns), not depth")

        if config.migration not in MIGRATIONS:
            self.refusals.append(f"migration must be one of {MIGRATIONS}")
        elif config.migration != "none":
            if self.z_domain is not ZDomain.DEPTH:
                self.refusals.append(
                    "migration needs the velocity of a scientifically sufficient depth model; "
                    "this volume would be time-domain")
            if g.missing_lines:
                self.refusals.append(
                    f"Stolt migration needs a complete regular grid; {len(g.missing_lines)} "
                    "line(s) are missing and would be treated as zero signal")
        if config.interpolation not in INTERPOLATIONS:
            self.refusals.append(f"interpolation must be one of {INTERPOLATIONS}")
        if config.max_gap_line_spacings < 1.0:
            self.refusals.append("max_gap_line_spacings must be >= 1 (one measured line spacing)")
        if config.background_removal not in ("none", "line_mean"):
            self.refusals.append("background_removal must be none or line_mean")

    # -- derived geometry ----------------------------------------------------
    @property
    def dx_m(self) -> float:
        return self.grid.trace_axis.step * self.grid.trace_axis.metres_per_unit()

    @property
    def dy_m(self) -> float:
        return self.grid.line_axis.step * self.grid.line_axis.metres_per_unit()

    @property
    def t0_ns(self) -> Optional[float]:
        return self.time_zero.correction_ns if (self.time_zero is not None
                                                and self.z_domain is ZDomain.DEPTH) else None

    @property
    def v(self) -> Optional[float]:
        return self.velocity.value_m_per_ns if (self.velocity and self.z_domain is ZDomain.DEPTH) else None

    def output_lines(self) -> np.ndarray:
        g = self.grid
        y0 = g.line_axis.origin * g.line_axis.metres_per_unit()
        y_last = y0 + (g.line_axis.n - 1) * self.dy_m
        s = self.config.output_line_spacing_m or self.dy_m
        n = int(np.floor((y_last - y0) / s + 1e-9)) + 1
        return y0 + np.arange(n) * s

    def z_axis(self) -> VolumeAxis:
        tax = self.grid.time_axis
        dt = tax.step
        t_last = tax.origin + (tax.n - 1) * dt
        if self.z_domain is ZDomain.DEPTH:
            offset = self._surface_offset_m()
            nz = int(np.floor((t_last - self.t0_ns) / dt + 1e-9)) + 1
            return VolumeAxis(name="depth", n=nz, origin=-offset, step=self.v * dt / 2.0, unit="m",
                              description="depth below the calibrated surface: "
                                          "v x (t - t0) / 2, constant velocity")
        return VolumeAxis(name="two_way_time", n=tax.n, origin=tax.origin, step=dt, unit="ns",
                          description="instrument two-way travel time; NOT depth; no time-zero "
                                      "correction applied")

    def _surface_offset_m(self) -> float:
        off = getattr(self.frame.vertical_axis, "origin_offset", None)
        if off is not None and off.relates_the_depth_axis:
            return float(off.offset_m)
        return 0.0

    def estimated_shape(self) -> Optional[tuple[int, int, int]]:
        if self.grid is None or self.frame is None:
            return None
        return (self.grid.trace_axis.n, int(self.output_lines().size), self.z_axis().n)

    # -- fingerprint ---------------------------------------------------------
    def components(self) -> dict[str, str]:
        from schemas.depth_model import DECLARATION_IDS_KEY
        from schemas.time_zero import APPLIED_TIME_ZERO_KEY

        f, g = self.frame, self.grid
        a = f.assumption(APPLIED_TIME_ZERO_KEY)
        ids = f.assumption(DECLARATION_IDS_KEY)
        return {
            "source_records": g.array_sha256[:16],
            "line_geometry": _h(g.model_dump(mode="json", exclude={"array_sha256", "array_file"})),
            "frame_registration": _h({"spatial_ref": f.spatial_ref.model_dump(mode="json"),
                                      "affine_tie": f.affine_tie.model_dump(mode="json") if f.affine_tie else None,
                                      "geo_tie": f.geo_tie.model_dump(mode="json") if f.geo_tie else None}),
            "velocity_depth_calibration": _h(f.vertical_axis.model_dump(mode="json")),
            "time_zero_declaration": _h(a.value if a is not None else None),
            "declarations": _h(ids.value if ids is not None else None),
            "preprocessing_and_migration": _h(self.config.model_dump(mode="json")),
            "method_version": RECONSTRUCTION_VERSION,
        }


# ---------------------------------------------------------------------------
# preview
# ---------------------------------------------------------------------------
def preview(dataset_id: str, config: VolumeConfig) -> dict:
    inp = Inputs(dataset_id, config)
    out = {"possible": not inp.refusals, "refusals": inp.refusals, "notes": inp.notes,
           "resolved": {}, "missing": []}
    if inp.grid is None or inp.frame is None:
        out["missing"] = ["a gridded acquisition (line identities, order, trace and line spacing)"]
        return out
    g = inp.grid
    out["resolved"] = {
        "frame_id": g.frame_id,
        "line_identities": f"{g.line_axis.n} lines indexed along {g.line_axis.name} "
                           f"({len(inp.measured_lines)} measured, {len(g.missing_lines)} missing)",
        "trace_spacing_m": inp.dx_m, "trace_spacing_source": g.trace_axis.source,
        "line_spacing_m": inp.dy_m, "line_spacing_source": g.line_axis.source,
        "line_order": g.traversal.value,
        "time_axis": f"{g.time_axis.n} samples x {g.time_axis.step:g} ns ({g.time_axis.source})",
        "coordinate_frame": _coordinate_frame(inp).model_dump(mode="json"),
    }
    out["depth"] = {"z_domain": inp.z_domain.value, "depth_scientifically_sufficient": inp.depth_ok,
                    "readiness": inp.readiness,
                    "velocity_m_per_ns": inp.velocity.value_m_per_ns if inp.velocity else None,
                    "time_zero_ns": inp.time_zero.correction_ns if inp.time_zero else None}
    if not inp.depth_ok:
        out["missing"].append("a scientifically sufficient depth model (for a DEPTH volume): "
                              + "; ".join(inp.readiness.get("reasons") or []))
    if not inp.refusals:
        shape = inp.estimated_shape()
        z = inp.z_axis()
        out["estimated_shape"] = shape
        out["voxel_spacing"] = (inp.dx_m, float(config.output_line_spacing_m or inp.dy_m), z.step)
        out["voxel_spacing_units"] = ("m", "m", z.unit)
        out["estimated_bytes"] = int(np.prod(shape)) * (4 + 4 + 1)
        lines = inp.output_lines()
        on_measured = sum(_nearest_measured(inp, y)[1] <= AT_LINE_TOLERANCE * inp.dy_m for y in lines)
        out["interpolation_required"] = bool(on_measured < lines.size)
        out["output_lines"] = {"n": int(lines.size), "at_measured_lines": int(on_measured)}
        if np.prod(shape) > MAX_VOXELS:
            out["possible"] = False
            out["refusals"].append(f"{np.prod(shape):,} voxels exceeds the {MAX_VOXELS:,} build limit")
    return out


def _nearest_measured(inp: Inputs, y_m: float) -> tuple[int, float]:
    ys = inp.grid.line_axis.origin * inp.grid.line_axis.metres_per_unit() + np.asarray(inp.measured_lines) * inp.dy_m
    k = int(np.argmin(np.abs(ys - y_m)))
    return inp.measured_lines[k], float(abs(ys[k] - y_m))


def _coordinate_frame(inp: Inputs) -> VolumeCoordinateFrame:
    f, g = inp.frame, inp.grid
    tu, lu = g.trace_axis.unit, g.line_axis.unit
    depth = inp.z_domain is ZDomain.DEPTH
    notes = []
    reg = None
    tie = f.affine_tie
    if tie is not None:
        # The tie maps the frame's own local units; the volume is in metres.
        sx, sy = 1.0 / g.trace_axis.metres_per_unit(), 1.0 / g.line_axis.metres_per_unit()
        reg = HorizontalRegistration(
            method="affine tie (frame declaration)", a=tie.a * sx, b=tie.b * sy, e=tie.e,
            c=tie.c * sx, d=tie.d * sy, f=tie.f, source=tie.supplied_by, verified=tie.verified,
            rms_residual_m=tie.rms_residual_m)
    else:
        notes.append("no horizontal registration declared: a local volume, not placed on the Earth "
                     "(none is invented)")
    notes.append("absolute elevation is not derived in Volume V1: z is relative to the "
                 "calibrated surface" if depth else "z is two-way time; no elevation")
    return VolumeCoordinateFrame(
        kind=CoordinateFrameKind.GEOREFERENCED if reg else CoordinateFrameKind.LOCAL,
        description=(f"survey frame {f.frame_id}: x along the lines ({g.trace_axis.name}, source "
                     f"{tu}), y across the lines ({g.line_axis.name}, source {lu}); metres "
                     f"from the grid origin; {f.spatial_ref.name or f.spatial_ref.kind.value}"),
        x_meaning=f"{g.trace_axis.name} position along each line, m ({g.trace_axis.source})",
        y_meaning=f"{g.line_axis.name} position of the line, m ({g.line_axis.source})",
        z_meaning=("depth below the surface, m (derived: constant velocity)" if depth
                   else "two-way travel time, ns (measured axis; NOT depth)"),
        z_origin=(("the surface defined by the frame's time zero ("
                   + (inp.time_zero.basis if inp.time_zero else "?") + ")") if depth
                  else "instrument time zero (raw sample 0)"),
        horizontal_registration=reg, absolute_elevation=False, notes=notes)


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------
def _preprocess(arr: np.ndarray, inp: Inputs) -> tuple[np.ndarray, list[ProcessingStep]]:
    dt = inp.grid.time_axis.step
    x = np.array(arr, dtype=np.float32, copy=True)
    steps = [ProcessingStep(name="acquisition_normalisation", applied=True, parameters={
        "order": "(trace along line, line, time) exactly as registered",
        "missing_lines": inp.grid.missing_lines, "amplitude": "raw stored values, float32"},
        note=inp.grid.amplitude_note)]
    if inp.config.dewow:
        w = max(3, int(round(DEWOW_NS / dt)))
        x -= uniform_filter1d(x, size=w, axis=2, mode="nearest")
        steps.append(ProcessingStep(name="dewow", applied=True,
                                    parameters={"running_mean_ns": DEWOW_NS, "samples": w},
                                    note="subtracts the low-frequency trend along each trace"))
    else:
        steps.append(ProcessingStep(name="dewow", applied=False))
    if inp.config.background_removal == "line_mean":
        x -= x.mean(axis=0, keepdims=True)
        steps.append(ProcessingStep(name="background_removal", applied=True,
                                    parameters={"method": "subtract each line's mean trace"},
                                    note="removes laterally constant energy, INCLUDING real flat "
                                         "reflectors such as a back wall"))
    else:
        steps.append(ProcessingStep(name="background_removal", applied=False))
    steps.append(ProcessingStep(name="gain", applied=False,
                                note="no gain is applied to the scientific field; display gain is "
                                     "a viewer setting"))
    if inp.grid.missing_lines:
        x[:, inp.grid.missing_lines, :] = 0.0     # placeholders only; never read as data below
    return x, steps


def _to_depth(x: np.ndarray, inp: Inputs, nz: int) -> tuple[np.ndarray, np.ndarray]:
    """Shift each trace so sample k sits at t0 + k dt. Returns (data, valid_z_mask)."""
    tax = inp.grid.time_axis
    s = (inp.t0_ns - tax.origin) / tax.step
    i0 = int(np.floor(s))
    w = np.float32(s - i0)
    idx = i0 + np.arange(nz)
    valid = (idx >= 0) & (idx + 1 < tax.n)
    idx_c = np.clip(idx, 0, tax.n - 2)
    out = (1 - w) * x[:, :, idx_c] + w * x[:, :, idx_c + 1]
    out[:, :, ~valid] = 0.0
    return out.astype(np.float32), valid


def build(dataset_id: str, config: VolumeConfig, created_by: Optional[str] = None) -> tuple[VolumeProduct, dict]:
    from database.grid_store import open_array
    from reconstruction.migration import spatial_aliasing_check, stolt_migrate

    t_start = time.perf_counter()
    inp = Inputs(dataset_id, config)
    if inp.refusals:
        raise VolumeRefused(inp.refusals)
    g = inp.grid
    zax = inp.z_axis()
    shape = inp.estimated_shape()
    if int(np.prod(shape)) > MAX_VOXELS:
        raise VolumeRefused([f"{int(np.prod(shape)):,} voxels exceeds the build limit"])

    raw = open_array(g)
    x, steps = _preprocess(raw, inp)
    timings = {"load_and_preprocess_s": time.perf_counter() - t_start}

    # --- C. axis ----------------------------------------------------------------
    if inp.z_domain is ZDomain.DEPTH:
        x, z_valid = _to_depth(x, inp, zax.n)
        steps.append(ProcessingStep(name="time_zero_and_depth", applied=True, parameters={
            "time_zero_ns": inp.t0_ns, "velocity_m_per_ns": inp.v, "dz_m": zax.step,
            "resampling": "sub-sample time shift by linear interpolation; dz = v dt / 2 so "
                          "each depth sample is one time sample"},
            note="depth = v (t - t0) / 2 from the frame's active, scientifically sufficient "
                 "depth model"))
    else:
        z_valid = np.ones(zax.n, bool)
        steps.append(ProcessingStep(name="time_zero_and_depth", applied=False,
                                    note="time-domain volume: raw two-way time, not depth"))

    # --- D. migration -------------------------------------------------------------
    mig = MigrationSpec(method="none", velocity_m_per_ns=inp.v,
                        velocity_source=(inp.velocity.basis.value if inp.velocity and inp.v else None),
                        time_zero_ns=inp.t0_ns,
                        time_zero_source=(inp.time_zero.status.value if inp.t0_ns is not None else None))
    t1 = time.perf_counter()
    if config.migration == "stolt_fk_3d":
        spec = np.abs(np.fft.rfft(x[::8, ::8, :], axis=2)).mean(axis=(0, 1))
        f = np.fft.rfftfreq(x.shape[2], d=g.time_axis.step)
        cum = np.cumsum(spec) / spec.sum()
        f_max = float(f[np.searchsorted(cum, 0.95)])
        alias = spatial_aliasing_check(inp.dx_m, inp.dy_m, inp.v, f_max)
        x = stolt_migrate(x, inp.dx_m, inp.dy_m, g.time_axis.step, inp.v, pad_xy=config.migration_padding)
        x[:, :, ~z_valid] = 0.0
        mig = mig.model_copy(update={"method": "stolt_fk_3d", "parameters": {
            "padding_traces_each_side": config.migration_padding, "time_padding_fraction": 0.25,
            "spectral_95pct_frequency_ghz": f_max, "aliasing": alias},
            "assumptions": ["zero offset", "constant velocity (the frame's calibrated / declared value)",
                            "exploding reflector (one-way velocity v/2)", "regular unaliased sampling"
                            + ("" if alias["unaliased"] else " -- VIOLATED: quarter-wavelength rule "
                                                             "not met; expect aliasing artefacts")]})
        if not alias["unaliased"]:
            inp.notes.append("spatial sampling is coarser than a quarter wavelength at the 95% "
                             "spectral frequency: migration may alias")
    timings["migration_s"] = time.perf_counter() - t1

    # --- E. grid formation --------------------------------------------------------------
    t2 = time.perf_counter()
    lines = inp.output_lines()
    ny_out = lines.size
    nx, nz = g.trace_axis.n, zax.n
    field = np.full((nx, ny_out, nz), np.nan, np.float32)
    support = np.zeros((nx, ny_out, nz), np.uint8)
    dist = np.full((nx, ny_out), np.nan, np.float32)
    count = np.zeros((nx, ny_out), np.uint8)
    y_meas = g.line_axis.origin * g.line_axis.metres_per_unit() + np.asarray(inp.measured_lines) * inp.dy_m
    max_gap = config.max_gap_line_spacings * inp.dy_m
    at_tol = AT_LINE_TOLERANCE * inp.dy_m
    at_class = SupportClass.RECONSTRUCTED if config.migration != "none" else SupportClass.MEASURED
    for jo, y in enumerate(lines):
        d = np.abs(y_meas - y)
        k = int(np.argmin(d))
        dmin = float(d[k])
        near = int(np.sum(d <= inp.dy_m + 1e-9))
        count[:, jo] = np.clip(near * 3, 0, 255)
        count[0, jo] = count[-1, jo] = np.clip(near * 2, 0, 255)
        dist[:, jo] = dmin
        if dmin <= at_tol:
            field[:, jo, :] = x[:, inp.measured_lines[k], :]
            support[:, jo, :] = at_class
            continue
        if config.interpolation == "nearest_no_fill":
            if dmin <= 0.5 * inp.dy_m:
                field[:, jo, :] = x[:, inp.measured_lines[k], :]
                support[:, jo, :] = SupportClass.INTERPOLATED
            continue
        lo = np.where(y_meas < y)[0]
        hi = np.where(y_meas > y)[0]
        if lo.size and hi.size:
            a, b = lo[-1], hi[0]
            gap = y_meas[b] - y_meas[a]
            if gap <= max_gap + 1e-9:
                wgt = np.float32((y - y_meas[a]) / gap)
                field[:, jo, :] = (1 - wgt) * x[:, inp.measured_lines[a], :] + wgt * x[:, inp.measured_lines[b], :]
                support[:, jo, :] = SupportClass.INTERPOLATED
    field[:, :, ~z_valid] = np.nan
    support[:, :, ~z_valid] = SupportClass.UNSUPPORTED
    field[support == SupportClass.UNSUPPORTED] = np.nan
    timings["gridding_s"] = time.perf_counter() - t2

    # --- F. derived envelope --------------------------------------------------------------
    t3 = time.perf_counter()
    env = np.abs(hilbert(np.nan_to_num(field), axis=2)).astype(np.float32)
    env[support == SupportClass.UNSUPPORTED] = np.nan
    timings["envelope_s"] = time.perf_counter() - t3

    vid = uuid.uuid4().hex[:12]
    migrated = config.migration != "none"
    depth = inp.z_domain is ZDomain.DEPTH
    fields = [
        PropertyField(
            property_name="radar_response", unit="arbitrary instrument amplitude units",
            value_kind="reconstructed" if migrated else "measured",
            description=("migrated (focused) radar response" if migrated else "radar response"),
            method=("Stolt F-K migration, constant velocity" if migrated else "measured samples")
                   + ("; dewow" if config.dewow else "")
                   + ("; line-mean background removal" if config.background_removal == "line_mean" else ""),
            uncertainty="amplitude has no calibrated physical unit; positions carry the depth "
                        "model's uncertainty" if depth else "time axis as recorded",
            evidence_sources=[f"frame {g.frame_id}", f"array sha256 {g.array_sha256[:16]}"],
            file="radar_response.npy", stats=_stats(field)),
        PropertyField(
            property_name="response_envelope", unit="arbitrary instrument amplitude units",
            value_kind="derived", description="instantaneous amplitude |Hilbert| of radar_response along z",
            method="analytic-signal magnitude along z", evidence_sources=["radar_response"],
            file="response_envelope.npy", stats=_stats(env)),
    ]
    summary = {c.name: int((support == c).sum()) for c in SupportClass}
    comps = inp.components()
    product = VolumeProduct(
        id=vid, dataset_id=dataset_id, source_dataset_ids=[dataset_id], frame_ids=[g.frame_id],
        coordinate_frame=_coordinate_frame(inp),
        x_axis=VolumeAxis(name="x", n=nx, origin=g.trace_axis.origin * g.trace_axis.metres_per_unit(),
                          step=inp.dx_m, unit="m", description=f"along-line ({g.trace_axis.name})"),
        y_axis=VolumeAxis(name="y", n=int(ny_out), origin=float(lines[0]),
                          step=float(lines[1] - lines[0]) if ny_out > 1 else inp.dy_m, unit="m",
                          description=f"across-line ({g.line_axis.name})"),
        z_axis=zax, z_domain=inp.z_domain, shape=(nx, int(ny_out), nz),
        voxel_spacing=(inp.dx_m, float(lines[1] - lines[0]) if ny_out > 1 else inp.dy_m, zax.step),
        fields=fields, primary_field="radar_response",
        support_file="support_class.npy", distance_file="nearest_distance.npy",
        count_file="support_count.npy", support_summary=summary,
        reconstruction_method=(("Stolt F-K 3D migration" if migrated else "no migration")
                               + f", {config.interpolation} gridding, "
                               + ("depth" if depth else "time") + " domain"),
        processing=steps, migration=mig,
        interpolation=InterpolationSpec(
            mode=config.interpolation, output_line_spacing_m=float(lines[1] - lines[0]) if ny_out > 1 else inp.dy_m,
            max_gap_m=max_gap,
            max_gap_rule=(f"interpolate across a gap only when <= {config.max_gap_line_spacings:g} measured "
                          "line spacings; nearest_no_fill assigns a measured line only within half a "
                          "spacing; everything else is UNSUPPORTED (empty)")),
        calibration_provenance=_calibration_provenance(inp), config=config,
        created_at=datetime.now(timezone.utc), created_by=created_by,
        source_fingerprint=_h(comps), input_components=comps, notes=inp.notes,
        performance={**{k: round(v, 3) for k, v in timings.items()},
                     "total_s": round(time.perf_counter() - t_start, 3),
                     "field_bytes": int(field.nbytes), "voxels": int(field.size)})
    arrays = {"radar_response.npy": field, "response_envelope.npy": env,
              "support_class.npy": support, "nearest_distance.npy": dist, "support_count.npy": count}
    return product, arrays


def _stats(a: np.ndarray) -> dict[str, float]:
    v = np.abs(a[np.isfinite(a)])
    if v.size == 0:
        return {}
    sample = v[:: max(1, v.size // 2_000_000)]
    p = np.percentile(sample, [50, 90, 95, 99, 99.9])
    return {"abs_p50": float(p[0]), "abs_p90": float(p[1]), "abs_p95": float(p[2]),
            "abs_p99": float(p[3]), "abs_p99_9": float(p[4]), "abs_max": float(v.max())}


def _calibration_provenance(inp: Inputs) -> dict:
    from schemas.depth_model import declaration_id_of

    conv = inp.frame.vertical_axis.conversion or {}
    return {"z_domain": inp.z_domain.value, "depth_readiness": inp.readiness,
            "velocity": inp.velocity.as_dict() if inp.velocity else None,
            "time_zero": inp.time_zero.model_dump(mode="json") if inp.time_zero else None,
            "calibration": conv.get("calibration"),
            "depth_calibration_declaration_id": declaration_id_of(inp.frame, "depth_calibration"),
            "used_for_depth": inp.z_domain is ZDomain.DEPTH,
            "support_class_meaning": {c.name: m for c, m in SUPPORT_CLASS_MEANING.items()}}


# ---------------------------------------------------------------------------
# staleness
# ---------------------------------------------------------------------------
COMPONENT_MEANING = {
    "source_records": "the stored measurements",
    "line_geometry": "the line geometry (spacing, order, missing lines)",
    "frame_registration": "the frame's coordinate reference or registration",
    "velocity_depth_calibration": "the velocity / depth calibration on the frame's axis",
    "time_zero_declaration": "the applied time zero",
    "declarations": "the active spatial declarations",
    "preprocessing_and_migration": "the preprocessing / migration configuration",
    "method_version": "the reconstruction method version",
}


def staleness(product: VolumeProduct) -> dict:
    """Compare the inputs now with those the volume was built from. Never rebuilds."""
    try:
        inp = Inputs(product.dataset_id, product.config)
        if inp.grid is None or inp.frame is None:
            return {"stale": True, "reasons": ["the source grid or frame no longer exists"]}
        now = inp.components()
    except Exception as exc:  # noqa: BLE001 -- report, never crash a read
        return {"stale": True, "reasons": [f"inputs could not be resolved: {exc}"]}
    changed = [k for k, v in product.input_components.items() if now.get(k) != v]
    return {"stale": bool(changed),
            "changed_components": changed,
            "reasons": [f"{COMPONENT_MEANING.get(k, k)} changed since this volume was built"
                        for k in changed],
            "action": ("regenerate the volume to use the current inputs (not done automatically)"
                       if changed else None)}
