"""
A 2D GPR survey scene and its rendering to a gprMax input file.

Scope, deliberately narrow for the first slice: a TM-mode 2D model, one
homogeneous soil half-space beneath air, circular-section targets (a pipe or
cable seen end-on), and a common-offset B-scan with both antennas ON the
ground surface. Each restriction is load-bearing for `truth.py`: with the
antennas on the surface and one homogeneous soil, every ray path lies in a
single medium, so the predicted travel time is exact geometry with no
refraction. Lifting any of them requires extending the truth model first.

Resolution and stability (cells per wavelength, the Courant limit) are NOT
re-checked here: gprMax computes them itself and refuses an under-resolved
model unless explicitly told otherwise, and a second, possibly divergent,
copy of that rule would only be a way to disagree with the solver.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field

C0 = 299_792_458.0  # m/s

# gprMax's default absorbing boundary is 10 cells thick on every face. A
# source, receiver or target inside it is not modelled as in open ground.
PML_CELLS = 10


@dataclass(frozen=True)
class Soil:
    name: str
    relative_permittivity: float
    conductivity: float  # S/m

    @property
    def velocity(self) -> float:
        """Propagation velocity, low-loss approximation c / sqrt(eps_r)."""
        return C0 / math.sqrt(self.relative_permittivity)


@dataclass(frozen=True)
class CircularTarget:
    """A target with a circular cross-section, infinitely long out of plane."""
    target_id: str
    label: str            # a schemas.subterra_record.GroundTruthLabel value
    centre_x: float
    centre_y: float
    radius: float
    material: str = "pec"  # gprMax built-in perfect electric conductor


@dataclass(frozen=True)
class Scenario2D:
    scenario_id: str
    title: str
    domain_x: float
    domain_y: float
    cell: float
    time_window: float     # s
    surface_y: float       # ground surface; soil below, air above
    soil: Soil
    centre_frequency: float  # Hz, Ricker
    tx_start_x: float
    antenna_offset: float  # rx_x - tx_x, metres
    step: float            # antenna move per trace, metres
    n_traces: int
    targets: tuple[CircularTarget, ...] = field(default_factory=tuple)

    def tx_x(self, trace: int) -> float:
        return self.tx_start_x + trace * self.step

    def rx_x(self, trace: int) -> float:
        return self.tx_x(trace) + self.antenna_offset

    def to_dict(self) -> dict:
        return asdict(self)

    def fingerprint(self) -> str:
        """SHA-256 of the canonical scene description."""
        canonical = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class ScenarioError(ValueError):
    """The scene cannot be simulated with truth this module can vouch for."""


def validate(s: Scenario2D) -> None:
    """Raise ScenarioError listing every geometric problem found."""
    problems: list[str] = []
    margin = PML_CELLS * s.cell

    if s.n_traces < 1:
        problems.append("n_traces must be at least 1")
    if not (margin < s.surface_y < s.domain_y - margin):
        problems.append("surface must lie inside the domain, clear of the absorbing boundary")

    xs = [s.tx_x(0), s.rx_x(0), s.tx_x(s.n_traces - 1), s.rx_x(s.n_traces - 1)]
    if min(xs) < margin or max(xs) > s.domain_x - margin:
        problems.append("antenna positions leave the domain or enter the absorbing boundary")

    seen: set[str] = set()
    for t in s.targets:
        if t.target_id in seen:
            problems.append(f"duplicate target_id {t.target_id!r}")
        seen.add(t.target_id)
        if t.radius <= 0:
            problems.append(f"{t.target_id}: radius must be positive")
        if t.centre_y + t.radius >= s.surface_y:
            problems.append(f"{t.target_id}: target is not entirely below the ground surface")
        if (t.centre_x - t.radius < margin or t.centre_x + t.radius > s.domain_x - margin
                or t.centre_y - t.radius < margin):
            problems.append(f"{t.target_id}: target enters the absorbing boundary or leaves the domain")

    if problems:
        raise ScenarioError("; ".join(problems))


def _fmt(v: float) -> str:
    return f"{v:.6g}"


def to_gprmax_input(s: Scenario2D) -> str:
    """Render the scene as a gprMax 4 input file (TM mode, 2D)."""
    validate(s)
    soil = s.soil
    lines = [
        f"#title: {s.title}",
        "#domain_mode: TM",
        f"#domain: {_fmt(s.domain_x)} {_fmt(s.domain_y)} inf",
        f"#dx_dy_dz: {_fmt(s.cell)} {_fmt(s.cell)} {_fmt(s.cell)}",
        f"#time_window: {_fmt(s.time_window)}",
        "",
        f"#material: {_fmt(soil.relative_permittivity)} {_fmt(soil.conductivity)} 1 0 {soil.name}",
        "",
        f"#waveform: ricker 1 {_fmt(s.centre_frequency)} src_wavelet",
        f"#hertzian_dipole: z {_fmt(s.tx_x(0))} {_fmt(s.surface_y)} inf src_wavelet",
        f"#rx: {_fmt(s.rx_x(0))} {_fmt(s.surface_y)} inf",
        f"#src_steps: {_fmt(s.step)} 0 0",
        f"#rx_steps: {_fmt(s.step)} 0 0",
        "",
        f"#box: 0 0 0 {_fmt(s.domain_x)} {_fmt(s.surface_y)} inf {soil.name}",
    ]
    for t in s.targets:
        lines.append(
            f"#cylinder: {_fmt(t.centre_x)} {_fmt(t.centre_y)} 0 "
            f"{_fmt(t.centre_x)} {_fmt(t.centre_y)} inf {_fmt(t.radius)} {t.material}"
        )
    return "\n".join(lines) + "\n"


# The gprMax project's own published 2D B-scan example
# (examples/gpr/basic/cylinder_Bscan_2D.in, v4.0.0), reproduced parameter for
# parameter. Starting from the solver's documented reference rather than a
# scene of our own means a wrong result is attributable to this module, not
# to an unusual model.
REFERENCE_CYLINDER_2D = Scenario2D(
    scenario_id="gprmax_reference_cylinder_bscan_2d",
    title="B-scan from a metal cylinder buried in a dielectric half-space",
    domain_x=0.240,
    domain_y=0.210,
    cell=0.002,
    time_window=3e-9,
    surface_y=0.170,
    soil=Soil(name="half_space", relative_permittivity=6.0, conductivity=0.0),
    centre_frequency=1.5e9,
    tx_start_x=0.040,
    antenna_offset=0.040,
    step=0.002,
    n_traces=60,
    targets=(
        CircularTarget(
            target_id="T1", label="pipe",
            centre_x=0.120, centre_y=0.080, radius=0.010, material="pec",
        ),
    ),
)

SCENARIOS: dict[str, Scenario2D] = {
    REFERENCE_CYLINDER_2D.scenario_id: REFERENCE_CYLINDER_2D,
}
