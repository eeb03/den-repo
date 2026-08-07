"""
Ingestion of the acquired BAM concrete GPR benchmark.

Reads the archives exactly as downloaded. Nothing is extracted in place,
nothing is rewritten, and no value is rescaled.

WHICH FILE THE AMPLITUDES COME FROM, and why it is not the DZT.

The archives carry the same measurement three ways: native GSSI `.DZT`,
per-line `.csv`, and a 3-D `.npy` volume. Only two of those can be tied to a
position:

    3D_Dataset_*.npy   shape (401, 161, 512)  == X x Y x samples, so it lines
                       up 1:1 with X-values.npy / Y-values.npy / Z-values.npy
    *.DZT              152,222 traces, which is NOT 401 x 161 = 64,561

No source documents how DZT traces map onto grid nodes. Guessing that mapping
would be inventing the very relationship the benchmark exists to test, so the
DZT is opened for its header -- proving the existing GSSI reader handles these
files, and recording acquisition parameters as provenance -- and the `.npy`
volume supplies the amplitudes that get scored. `benchmark.gates` carries this
as the open question `dzt-to-grid-mapping`.

WHAT IS DELIBERATELY NOT DONE HERE: no CRS is assigned, no absolute origin is
assumed, no coordinate is converted to a global frame, and no physical unit is
attached to a number whose file does not declare one. The grid is carried as
`source coordinates`, which is not the same thing as verified global physical
coordinates, and `GridSpec` keeps that distinction in the type itself.
"""
from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

DEFAULT_ROOT = Path("datasets/raw/bam_concrete")

#: The grid the benchmark documents and the acquisition verified from the
#: files. Recorded as an expectation so ingestion FAILS on a file that does not
#: match, rather than silently scoring a differently-shaped volume.
EXPECTED_GRID = {
    "n_x": 401, "x_first": 0, "x_last": 2000, "x_step": 5,
    "n_y": 161, "y_first": 0, "y_last": 800, "y_step": 5,
    "n_z": 512,
}


class BenchmarkIngestError(RuntimeError):
    """Raised when the archive does not match what the benchmark documents."""


@dataclass(frozen=True)
class GridSpec:
    """
    The benchmark's own measuring grid, in the benchmark's own numbers.

    `x`, `y` and `z` are the source values, unchanged. `units_*` is what the
    publisher's prose says they are -- carried separately, and tagged, because
    no file in the archive declares a unit. Anything reported in physical units
    rather than grid nodes is relying on `units_provenance`, not on the data.
    """
    x: np.ndarray
    y: np.ndarray
    z: np.ndarray
    units_xy: str = "mm"
    units_z: str = "ns"
    units_provenance: str = "inferred_from_documentation"
    units_note: str = (
        "The .npy arrays carry no unit and no file in either archive declares "
        "one; mm/ns come from the Dataverse description. The nanosecond unit is "
        "independently corroborated by the DZT header (range_ns=15.0, "
        "n_samples=512); millimetres have no such corroboration."
    )
    #: No CRS. Not unknown-and-to-be-determined -- there is no CRS to have.
    crs: Optional[str] = None
    crs_provenance: str = "none"
    absolute_origin_verified: bool = False
    frame: str = "benchmark-local; X along specimen length, Y across width, Z two-way time"

    @property
    def x_step(self) -> float:
        return float(np.diff(self.x)[0])

    @property
    def y_step(self) -> float:
        return float(np.diff(self.y)[0])

    def x_node(self, x_value: float) -> int:
        """
        The grid index of a source X value.

        Exact only. A value that does not land on a node raises rather than
        rounding, because rounding here would silently turn an exact
        association into a nearest-neighbour one.
        """
        hits = np.flatnonzero(self.x == x_value)
        if hits.size != 1:
            raise BenchmarkIngestError(
                f"x={x_value} is not a grid node; nearest-neighbour matching is "
                f"not permitted for benchmark association"
            )
        return int(hits[0])

    def as_dict(self) -> dict:
        return {
            "n_x": int(self.x.size), "x_first": float(self.x[0]),
            "x_last": float(self.x[-1]), "x_step": self.x_step,
            "n_y": int(self.y.size), "y_first": float(self.y[0]),
            "y_last": float(self.y[-1]), "y_step": self.y_step,
            "n_z": int(self.z.size), "z_first": float(self.z[0]),
            "z_last": float(self.z[-1]),
            "units_xy": self.units_xy, "units_z": self.units_z,
            "units_provenance": self.units_provenance,
            "crs": self.crs, "crs_provenance": self.crs_provenance,
            "absolute_origin_verified": self.absolute_origin_verified,
            "frame": self.frame,
        }


@dataclass(frozen=True)
class BenchmarkScan:
    """One antenna/polarisation configuration of one specimen."""
    benchmark_id: str
    specimen_id: str
    scan_id: str
    archive: str
    volume_member: str
    grid: GridSpec
    dzt_header: dict = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)

    @property
    def n_traces_per_line(self) -> int:
        return int(self.grid.x.size)

    @property
    def n_lines(self) -> int:
        return int(self.grid.y.size)


def _load_npy(zf: zipfile.ZipFile, member: str) -> np.ndarray:
    return np.load(io.BytesIO(zf.read(member)))


def _find(zf: zipfile.ZipFile, suffix: str) -> str:
    hits = [n for n in zf.namelist() if n.endswith(suffix)]
    if len(hits) != 1:
        raise BenchmarkIngestError(f"expected exactly one member ending {suffix!r}, found {len(hits)}")
    return hits[0]


def load_grid(archive: Path) -> GridSpec:
    """The X/Y/Z vectors, exactly as the archive stores them."""
    with zipfile.ZipFile(archive) as zf:
        grid = GridSpec(
            x=_load_npy(zf, _find(zf, "3D_Dataset_NPY_Data/X-values.npy")),
            y=_load_npy(zf, _find(zf, "3D_Dataset_NPY_Data/Y-values.npy")),
            z=_load_npy(zf, _find(zf, "3D_Dataset_NPY_Data/Z-values.npy")),
        )
    _check_grid(grid, archive)
    return grid


def _check_grid(grid: GridSpec, archive: Path) -> None:
    got = {
        "n_x": int(grid.x.size), "x_first": int(grid.x[0]), "x_last": int(grid.x[-1]),
        "x_step": int(grid.x_step),
        "n_y": int(grid.y.size), "y_first": int(grid.y[0]), "y_last": int(grid.y[-1]),
        "y_step": int(grid.y_step),
        "n_z": int(grid.z.size),
    }
    bad = {k: (v, EXPECTED_GRID[k]) for k, v in got.items() if v != EXPECTED_GRID[k]}
    if bad:
        raise BenchmarkIngestError(
            f"{archive.name}: grid does not match the documented benchmark grid: "
            + ", ".join(f"{k} got {g} expected {e}" for k, (g, e) in bad.items())
        )
    for name, arr in (("x", grid.x), ("y", grid.y)):
        d = np.diff(arr)
        if not np.all(d == d[0]):
            raise BenchmarkIngestError(f"{archive.name}: {name} spacing is not uniform")


def read_dzt_header(archive: Path, scan_id: str) -> dict:
    """
    Open the native DZT with the EXISTING GSSI reader.

    This is a compatibility and provenance step, not the amplitude source --
    see the module docstring. Only the header is staged.
    """
    import tempfile

    from converters.gssi_converter import parse_dzt_header

    with zipfile.ZipFile(archive) as zf:
        member = _find(zf, f"Radar_DZT_Data/{scan_id}.DZT")
        with zf.open(member) as src, tempfile.NamedTemporaryFile(suffix=".DZT") as tmp:
            tmp.write(src.read(1 << 20))
            tmp.flush()
            header = parse_dzt_header(tmp.name)
        member_size = zf.getinfo(member).file_size

    n_samples = int(header.get("n_samples", 0)) or 1
    bits = int(header.get("bits", 16))
    offset = int(header.get("data_offset", 0))
    bytes_per_trace = n_samples * (bits // 8)
    dzt_traces = (member_size - offset) // bytes_per_trace if bytes_per_trace else None

    return {
        "member": member.split("/")[-1],
        "read_by": "converters.gssi_converter.parse_dzt_header",
        "n_samples": header.get("n_samples"),
        "range_ns": header.get("range_ns"),
        "bits": header.get("bits"),
        "epsr": header.get("epsr"),
        "antenna_name_in_header": header.get("antenna_name"),
        "scans_per_metre": header.get("scans_per_metre"),
        "dzt_trace_count": int(dzt_traces) if dzt_traces else None,
        "grid_trace_count": EXPECTED_GRID["n_x"] * EXPECTED_GRID["n_y"],
        "dzt_matches_grid": bool(dzt_traces == EXPECTED_GRID["n_x"] * EXPECTED_GRID["n_y"]),
        "amplitude_source": "3D_Dataset_NPY_Data (NOT this DZT)",
        "why": (
            "The DZT trace count does not equal the coordinate-registered grid "
            "and no source documents the mapping; see benchmark.gates open "
            "question 'dzt-to-grid-mapping'."
        ),
        "header_filename_conflict": (
            "DZT header antenna name and the filename disagree; recorded, not resolved"
            if header.get("antenna_name") and scan_id and
            header["antenna_name"].replace(".", "_").replace("GHz", "") not in scan_id
            else None
        ),
    }


def _provenance(root: Path, archive: Path) -> dict:
    """Source identity for every artifact this ingestion produces."""
    prov_path = root / "PROVENANCE.json"
    if not prov_path.exists():
        return {"warning": f"no PROVENANCE.json beside {archive.name}"}
    prov = json.loads(prov_path.read_text())
    entry = next((f for f in prov["files"] if f["filename"] == archive.name), None)
    return {
        "doi": prov["doi"],
        "repository": prov["publisher"],
        "licence": prov["licence"],
        "licence_source": prov["licence_source"],
        "archive": archive.name,
        "archive_md5": entry["md5"] if entry else None,
        "archive_md5_verified": entry["md5_verified"] if entry else None,
        "archive_sha256": entry["sha256"] if entry else None,
        "source_files_unmodified": True,
    }


def load_scan(specimen_id: str, scan_id: str, root: Path = DEFAULT_ROOT) -> BenchmarkScan:
    """Metadata and grid for one configuration. Does not load the volume."""
    archive = root / f"{specimen_id}_Dataset.zip"
    if not archive.exists():
        raise BenchmarkIngestError(f"benchmark archive not present: {archive}")

    grid = load_grid(archive)
    with zipfile.ZipFile(archive) as zf:
        volume_member = _find(zf, f"3D_Dataset_NPY_Data/{scan_id}.npy")

    return BenchmarkScan(
        benchmark_id="bam-concrete-gpr",
        specimen_id=specimen_id,
        scan_id=scan_id,
        archive=archive.name,
        volume_member=volume_member,
        grid=grid,
        dzt_header=read_dzt_header(archive, scan_id.replace("_3D_Dataset", "")),
        provenance=_provenance(root, archive),
    )


def load_volume(scan: BenchmarkScan, root: Path = DEFAULT_ROOT) -> np.ndarray:
    """
    The amplitude volume, shape (n_x, n_y, n_samples), values unchanged.

    Raises if the shape disagrees with the grid, so a mismatched file can
    never be scored as if it lined up.
    """
    archive = root / scan.archive
    with zipfile.ZipFile(archive) as zf:
        vol = _load_npy(zf, scan.volume_member)
    expected = (scan.grid.x.size, scan.grid.y.size, scan.grid.z.size)
    if vol.shape != expected:
        raise BenchmarkIngestError(
            f"{scan.volume_member}: volume shape {vol.shape} does not match the "
            f"grid {expected}"
        )
    return vol


def line_traces(volume: np.ndarray, y_index: int) -> np.ndarray:
    """
    One B-scan as (n_traces, n_samples), ready for the existing preprocessing.

    A "line" is one Y position: the antenna's traverse along X at fixed Y, so
    trace index == X grid node. That identity is what makes the association
    exact rather than nearest-neighbour.
    """
    return np.asarray(volume[:, y_index, :], dtype=float)
