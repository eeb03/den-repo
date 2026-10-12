"""
How a simulated acquisition enters the platform's EXISTING data and
interpretation paths -- and where it must not go.

THE TWO KINDS OF SYNTHETIC ACQUISITION, and why they are never mixed.

* INDEPENDENT_2D_PROFILE -- what the corpus holds today. gprMax runs in 2D
  TM mode: every target is an infinitely long cylinder perpendicular to the
  line, and each scene is its own world. Two profiles are NOT two slices
  through one ground: nothing relates their positions, and interpolating
  between them would invent a volume no simulation computed. A profile is a
  radargram, and only a radargram.
* GRIDDED_3D_VOLUME -- reserved for gprMax 3D runs (roadmap M2/M3), where
  many lines are acquired over ONE model and share its frame. Nothing
  produces this kind yet, so nothing here accepts it; the schema it will
  feed (`SubsurfaceVolume`) does not exist yet either.

WHERE A PROFILE GOES, all existing code, nothing rebuilt:

* the array path -- `SyntheticLine.traces` is (n_traces, n_samples), the
  input `preprocessing.spatial_grid.anomaly_grid_from_traces` and
  `benchmark.detection.detect_line` already take;
* the record path -- `to_subterra_records` emits one `SubterraRecord` per
  (trace, sample), the shape `SEGYConverter` emits, so
  `process_gpr_traces` -> `preprocess_trace_local_anomaly` ->
  `find_anomaly_candidates` and the radargram view run unchanged.

WHERE IT MUST NOT GO.

* The 3D scene (`schemas.scene.ScenePayload`). A profile has a
  model-local x and no geographic or vertical reference, so
  `schemas.views._scene_3d` correctly leaves it unresolved; no Earth
  position is invented to change that.
* Ground truth on records or objects. Simulated truth stays in truth.json
  and is used for SCORING only. It is never written to
  `SubterraRecord.ground_truth`, never becomes an attested
  `SubsurfaceObject`, and never counts toward the platform's real-label
  tally: a result measured on simulation is a simulation result.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import numpy as np

from schemas.depth_model import two_way_time_to_depth
from schemas.radargram import VelocitySource
from schemas.spatial import LocalCartesianPosition
from schemas.subterra_record import SensorType, SubterraRecord


class AcquisitionKind(str, Enum):
    INDEPENDENT_2D_PROFILE = "independent_2d_profile"
    GRIDDED_3D_VOLUME = "gridded_3d_volume"  # reserved; nothing produces it yet


#: Only acquisitions that share one model frame may ever be built into a
#: volume. A set of independent 2D profiles never qualifies.
VOLUME_ELIGIBLE = frozenset({AcquisitionKind.GRIDDED_3D_VOLUME})

VELOCITY_ATTRIBUTION = "simulation input: the soil permittivity the solver was given (exact by construction)"


@dataclass(frozen=True)
class SyntheticLine:
    """One simulated profile, in the shapes the existing pipeline takes."""
    scenario_id: str
    acquisition_kind: AcquisitionKind
    traces: np.ndarray          # (n_traces, n_samples), Ez
    background: np.ndarray      # same shape: the target-free twin
    dt_s: float
    time_offset_s: float
    midpoint_x_m: np.ndarray    # (n_traces,) model-local, not geographic
    soil_velocity_m_per_s: float
    truth: dict                 # truth.json; for scoring only

    @property
    def sample_times_s(self) -> np.ndarray:
        return np.arange(self.traces.shape[1]) * self.dt_s + self.time_offset_s


def volume_eligibility(kind: AcquisitionKind) -> tuple[bool, str]:
    if kind in VOLUME_ELIGIBLE:
        return True, "acquired over one shared model frame"
    return False, ("independent 2D profiles share no frame; stacking or interpolating "
                   "them would fabricate a volume no simulation computed")


def load_line(artifact_dir: Path) -> SyntheticLine:
    """Read a corpus artifact written by simulation.run_gprmax."""
    manifest = json.loads((artifact_dir / "manifest.json").read_text())
    truth = json.loads((artifact_dir / "truth.json").read_text())
    if not manifest.get("simulated"):
        raise ValueError(f"{artifact_dir}: not a simulated artifact")
    d = np.load(artifact_dir / "bscan.npz")
    tx, rx = np.asarray(truth["antennas"]["tx_x_m"]), np.asarray(truth["antennas"]["rx_x_m"])
    return SyntheticLine(
        scenario_id=manifest["scenario_id"],
        # Every artifact run_gprmax writes is a 2D TM model.
        acquisition_kind=AcquisitionKind.INDEPENDENT_2D_PROFILE,
        traces=d["data"].astype(np.float64).T,
        background=d["background"].astype(np.float64).T,
        dt_s=float(d["dt"]),
        time_offset_s=float(d["time_offset"]),
        midpoint_x_m=(tx + rx) / 2,
        soil_velocity_m_per_s=float(truth["medium"]["velocity_m_per_s"]),
        truth=truth,
    )


def to_subterra_records(line: SyntheticLine, dataset_id: str) -> list[SubterraRecord]:
    """One record per (trace, sample), as SEGYConverter writes a GPR line.

    Depth uses the soil velocity the solver was given, tagged DECLARED with
    its attribution: in a simulation it is known, not assumed. Position is
    model-local x along the line (`LocalCartesianPosition`, y = 0); no
    latitude/longitude exists and none is made up."""
    if line.acquisition_kind is not AcquisitionKind.INDEPENDENT_2D_PROFILE:
        raise ValueError(f"unsupported acquisition kind {line.acquisition_kind}")
    v_m_per_ns = line.soil_velocity_m_per_s * 1e-9
    times_ns = line.sample_times_s * 1e9
    frame_id = f"sim:{line.scenario_id}"
    records = []
    for trace_idx, trace in enumerate(line.traces):
        position = LocalCartesianPosition(x=float(line.midpoint_x_m[trace_idx]), y=0.0)
        for sample_idx, value in enumerate(trace):
            records.append(SubterraRecord(
                dataset_id=dataset_id,
                sensor_type=SensorType.GPR,
                position=position,
                frame_id=frame_id,
                depth=two_way_time_to_depth(float(times_ns[sample_idx]), v_m_per_ns),
                signal=[float(value)],
                ground_truth="none",  # simulated truth is for scoring only
                metadata={
                    "source_file": line.scenario_id,
                    "trace_index": trace_idx,
                    "sample_index": sample_idx,
                    "two_way_time_ns": float(times_ns[sample_idx]),
                    "velocity_m_per_ns": v_m_per_ns,
                    "velocity_source": VelocitySource.DECLARED.value,
                    "velocity_attribution": VELOCITY_ATTRIBUTION,
                    "sample_interval": line.dt_s * 1e9,
                    "simulated": True,
                    "acquisition_kind": line.acquisition_kind.value,
                },
            ))
    return records
