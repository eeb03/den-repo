"""
Self-Supervised GPR Encoder V1: real unlabelled-corpus discovery, the
site-level train/validation/reserved policy, reproducible window
construction, and raw-amplitude window materialisation.

============================================================================
THE AUDIT THIS MODULE IS BUILT AGAINST
============================================================================

Every dataset `docs/dataset-inventory.md` already documents on disk was
re-checked directly against real files (not the doc's summary alone) for
what THIS milestone needs: real multi-sample GPR traces, a licence that
states whether commercial model training is permitted, and enough real
files to window.

  bam-concrete-gpr   CC0-1.0, commercial use explicitly permitted. 8 real
                     3-D volumes (2 specimens x 2 frequencies x 2
                     rotations), (401, 161, 512) each -- windowed here by
                     slicing along Y into 401-trace x 512-sample real
                     lines (see `discover_bam_source_files`). By far the
                     largest real signal held.
  4tu-nl-utility     CC0-1.0, commercial use explicitly permitted. 759 real
                     little-endian SEG-Y files across 13 REAL, DISTINCT
                     sites (directories `01`..`013` under the archive's own
                     `extracted/`) -- the corpus's only dataset with enough
                     independent real sites to support a genuine site-level
                     SSL validation/reserved split.
  tu1208-ifsttar     CC-BY-4.0, commercial use permitted with attribution.
                     40 native GSSI + 15 native MALA files (the 12 IDS
                     `.dt` files are OUT OF SCOPE for V1 -- see "what this
                     module does not read" below). One real site.
  hillside-lancaster CC-BY-4.0, commercial use permitted with attribution.
                     321 native MALA files. One real site.
  testum (PANGAEA    CC-BY-4.0, commercial use permitted with attribution.
  971978)            Only 2 of the archive's 293 files are locally held
                     (`docs/testum-raw-data-validation.md`) -- both native
                     GSSI. Small, but genuinely real and independent of
                     every other held site (different institution,
                     different acquisition context) -- see
                     `RESERVED_DATASETS` for why this is the one dataset
                     sealed out of SSL entirely.

  EXCLUDED, and why (never silently combined into the corpus above):

  grimsel (AU-tunnel  Real GPR file held (`GPR_AU_N-to-S.rd3`), but its
  GPR, .rd3)          licence is "In Copyright -- Non-Commercial Use
                      Permitted" (`docs/grimsel-deep-evidence-audit.md`
                      section F) -- RESEARCH-ONLY pool, never the
                      commercial-compatible one.
  ingv-unisa          License field is literally UNVERIFIED
                      (`docs/dataset-inventory.md`'s own line for it) --
                      an unverified licence is treated as RESEARCH_ONLY,
                      not "probably fine" (this module's own
                      `LicensePool` docstring). Also structurally
                      unusable regardless: live-checked this session,
                      every held record has `samples_per_trace: null` --
                      single-value-per-record data, not a multi-sample
                      trace a 2-D window can be cut from.
  guangzhou-ids       CC-BY-4.0 (commercial-compatible), but only 10 `.dt`
                      files are held locally and the format is out of
                      scope for V1 (see below) -- excluded for scope, not
                      licence.

============================================================================
WHAT THIS MODULE DOES NOT READ (a scope decision, not a blocker)
============================================================================

IDS `.dt` files (TU1208's 12, Guangzhou's 10 -- 22 files, a small fraction
of the held corpus) are not read by this module. Every other real format
held (little-endian SEG-Y, native GSSI `.DZT`, native MALA `.rd3`, BAM's
own `.npy` volumes) already has a low-level reader in `converters/` this
module reuses directly; adding a fourth format's low-level dispatch for 22
files is deferred to a future SSL revision, not attempted here to keep V1
disciplined (brief Section 20's own "model-size [and scope] discipline").

============================================================================
SITE-LEVEL POLICY (Section 3)
============================================================================

Two DIFFERENT real risks are kept distinct, per the brief's own instruction
not to blur them:

1. Corpus-wide RESERVATION: `testum` is held out of SSL training AND
   validation entirely. Its signal is never touched by this milestone. A
   future evaluation against it may honestly claim `UNSEEN_SITE`.
2. Within-4tu SITE-LEVEL split: 4TU is the one dataset with enough real,
   independent sites (13) to support this without inventing site
   boundaries. Sites `012`/`013` are RESERVED (sealed, same guarantee as
   testum); `010`/`011` are SSL VALIDATION (monitored during pretraining,
   never trained on); `01`-`09` are SSL TRAIN. The split is by SITE
   (a real 4TU project/location), never by file within a site, so a
   validation-site file cannot share acquisition-day/instrument-state
   correlation with a training-site file the way two files from the SAME
   site could.

For `tu1208-ifsttar`, `hillside-lancaster` and `bam-concrete-gpr`, there is
only ONE real site (`tu1208-ifsttar`, `hillside-lancaster`) or one lab/
fabricator behind both specimens (BAM) -- a genuine site-level split is not
constructible from one site, the same structural fact
`training.segmentation.assess_split_adequacy` already encodes for the
labelled corpus. A deterministic FILE-level (BAM: real specimen; TU1208/
Hillside: sorted filename) validation subset is held out for loss
monitoring instead, but is recorded with `SiteExposure.
UNSEEN_LABELS_SEEN_ACQUISITION` -- explicitly NOT `UNSEEN_SITE` -- because
the site's signal distribution was seen during SSL training via its other
files. Reported as exactly that distinction in every place this matters,
never conflated.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from converters import gssi_converter, mala_converter, segy_endian
from schemas.ssl_gpr import LicensePool, SiteExposure, SiteSplit, SSLSourceFile, SSLWindowRef

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# corpus roots -- real, on-disk locations `docs/dataset-inventory.md` names
# ---------------------------------------------------------------------------

BAM_ROOT = REPO_ROOT / "datasets/raw/bam_concrete"
FOURTU_ROOT = REPO_ROOT / "datasets/raw/4tu/96303227-5886-41c9-8607-70fdd2cfe7c1/extracted"
TU1208_ROOT = REPO_ROOT / "datasets/raw/zenodo/1211173/extracted/Database_2018"
HILLSIDE_ROOT = REPO_ROOT / "datasets/raw/zenodo/8253179/extracted"
TESTUM_ROOT = REPO_ROOT / "datasets/raw/pangaea/971978/raw"
GRIMSEL_ROOT = REPO_ROOT / "datasets/raw/grimsel/ethz-b-000420930"

#: Real BAM scan configurations (`benchmark.bam_ingest.load_scan`'s own
#: `scan_id` argument) -- the 8 volumes confirmed on disk this session (see
#: this module's own docstring).
BAM_SPECIMENS = ("Pk266", "Pk050")
BAM_SCAN_IDS = (
    "1_5_GHz_Rot00", "1_5_GHz_Rot90", "2_6_GHz_Rot00", "2_6_GHz_Rot90",
)
#: Every 8th Y-line -- real data, not fabricated, but bounds the corpus to a
#: tractable size (161 Y-indices x 8 volumes would be 1,288 real lines per
#: specimen pair; this keeps a V1 CPU training run's runtime bounded without
#: dropping any specimen, frequency or rotation from representation).
BAM_Y_STRIDE = 8

#: The 4TU site directories actually on disk (`01`..`013`), and the
#: deterministic split this module's own docstring documents. Recorded as
#: data, not re-derived from a rule scattered through the code, so the
#: exact policy is inspectable in one place.
FOURTU_RESERVED_SITES = ("012", "013")
FOURTU_VALIDATION_SITES = ("010", "011")
# every other real site directory present -> TRAIN (computed in
# `discover_fourtu_source_files`, not hand-listed, so a site added to the
# archive later is never silently dropped from training).

#: Held out of SSL training AND validation entirely -- see this module's
#: own "SITE-LEVEL POLICY" section for why.
RESERVED_DATASETS = ("testum",)


def _license_pool(commercial_use_permitted: Optional[bool]) -> LicensePool:
    return (
        LicensePool.COMMERCIAL_COMPATIBLE
        if commercial_use_permitted is True
        else LicensePool.RESEARCH_ONLY
    )


# ---------------------------------------------------------------------------
# discovery -- one function per real dataset, each reading real headers only
# (cheap: a few hundred bytes per file), never the full sample data
# ---------------------------------------------------------------------------

def discover_bam_source_files(root: Path = BAM_ROOT) -> list[SSLSourceFile]:
    """
    One `SSLSourceFile` per (specimen, scan_id, sampled Y-line) -- see
    `BAM_Y_STRIDE`. `bam-Pk266` is SSL TRAIN; `bam-Pk050` is SSL VALIDATION
    (`UNSEEN_LABELS_SEEN_ACQUISITION`: a different real specimen, same
    fabricator/lab/instrument as Pk266, so this is cross-acquisition
    monitoring, not a site-generalisation claim).
    """
    from benchmark import bam_ingest
    from scripts.bam_hyperbola_velocity_audit import establish_time_axis

    out: list[SSLSourceFile] = []
    for specimen in BAM_SPECIMENS:
        archive = root / f"{specimen}_Dataset.zip"
        if not archive.exists():
            continue
        split = SiteSplit.TRAIN if specimen == "Pk266" else SiteSplit.VALIDATION
        for scan_id in BAM_SCAN_IDS:
            full_scan_id = f"{specimen}_3D_Dataset_{scan_id}"
            try:
                scan = bam_ingest.load_scan(specimen, full_scan_id, root=root)
            except Exception:
                continue  # a scan config this specimen's archive does not carry
            n_x, n_y = scan.grid.x.size, scan.grid.y.size
            sample_interval_ns = establish_time_axis(scan).sample_interval_ns
            for y in range(0, n_y, BAM_Y_STRIDE):
                out.append(SSLSourceFile(
                    dataset_id="bam-concrete-gpr", site_id=f"bam-{specimen}",
                    survey_id=full_scan_id, source_file=scan.archive, reader="bam_npy_yslice",
                    sensor_vendor="GSSI",
                    antenna_frequency_mhz=2600.0 if "2_6_GHz" in scan_id else 1500.0,
                    sample_interval_ns=sample_interval_ns,
                    n_traces=n_x, n_samples=scan.grid.z.size, line_index=y,
                    license="CC0-1.0", commercial_use_permitted=True,
                    license_pool=LicensePool.COMMERCIAL_COMPATIBLE,
                    split=split, exposure=SiteExposure.UNSEEN_LABELS_SEEN_ACQUISITION,
                ))
    return out


def discover_fourtu_source_files(root: Path = FOURTU_ROOT) -> list[SSLSourceFile]:
    """
    One `SSLSourceFile` per real `.sgy` file across all 13 on-disk site
    directories, header-only (`LittleEndianSegyFile` reads only the binary
    header + a size computation, never trace data, to get `n_traces`/
    `n_samples`). Site membership assigns the split -- see this module's
    docstring.
    """
    out: list[SSLSourceFile] = []
    if not root.exists():
        return out
    for site_dir in sorted(p for p in root.iterdir() if p.is_dir() and re.fullmatch(r"0\d+", p.name)):
        site_id = site_dir.name
        if site_id in FOURTU_RESERVED_SITES:
            split, exposure = SiteSplit.RESERVED, SiteExposure.UNSEEN_SITE
        elif site_id in FOURTU_VALIDATION_SITES:
            split, exposure = SiteSplit.VALIDATION, SiteExposure.UNSEEN_SITE
        else:
            split, exposure = SiteSplit.TRAIN, SiteExposure.UNSEEN_LABELS_SEEN_ACQUISITION
        for sgy_path in sorted(site_dir.rglob("*.sgy")):
            try:
                f = segy_endian.LittleEndianSegyFile(sgy_path)
            except Exception:
                continue
            out.append(SSLSourceFile(
                dataset_id="4tu-nl-utility", site_id=f"4tu-{site_id}",
                survey_id=sgy_path.parent.name,
                source_file=str(sgy_path.relative_to(REPO_ROOT)), reader="segy_le",
                sensor_vendor="unrecorded (air-launched, per dataset inventory)",
                antenna_frequency_mhz=500.0, sample_interval_ns=f.interval / 1000.0,
                n_traces=f.tracecount, n_samples=f.n_samples,
                license="CC0-1.0", commercial_use_permitted=True,
                license_pool=LicensePool.COMMERCIAL_COMPATIBLE,
                split=split, exposure=exposure,
            ))
            f._fh.close()
    return out


def _file_level_split(paths: list[Path], validation_fraction: float = 0.1) -> dict[Path, SiteSplit]:
    """
    Deterministic, sorted-filename tail as SSL validation -- the fallback
    used for a dataset with only one real site (see this module's docstring
    for why this is `UNSEEN_LABELS_SEEN_ACQUISITION`, never `UNSEEN_SITE`).
    """
    ordered = sorted(paths)
    n_val = max(1, round(len(ordered) * validation_fraction)) if ordered else 0
    val_set = set(ordered[-n_val:]) if n_val else set()
    return {p: (SiteSplit.VALIDATION if p in val_set else SiteSplit.TRAIN) for p in ordered}


def discover_tu1208_source_files(root: Path = TU1208_ROOT) -> list[SSLSourceFile]:
    """
    Native GSSI (`.DZT`/`.dzt`) and MALA (`.rd3`) files under `Database_2018`
    -- the 12 IDS `.dt` files are out of scope for V1 (module docstring).
    One real site (`ifsttar`); split is file-level (`_file_level_split`).
    """
    out: list[SSLSourceFile] = []
    if not root.exists():
        return out

    dzt_paths = sorted(root.rglob("*.[dD][zZ][tT]"))
    rd3_paths = sorted(p for p in root.rglob("*.[rR][dD]3"))
    split_by_path = _file_level_split(dzt_paths) | _file_level_split(rd3_paths)

    for path in dzt_paths:
        try:
            header = gssi_converter.parse_dzt_header(path)
            axis = gssi_converter.derive_time_axis(header, path)
        except Exception:
            continue
        n_traces = (path.stat().st_size - header["data_offset"]) // (
            header["n_samples"] * {16: 2, 8: 1, 32: 4}.get(header["bits"], 2)
        )
        if n_traces < 1:
            continue
        out.append(SSLSourceFile(
            dataset_id="tu1208-ifsttar", site_id="tu1208-ifsttar",
            survey_id=path.stem, source_file=str(path.relative_to(REPO_ROOT)), reader="gssi_dzt",
            sensor_vendor="GSSI", antenna_frequency_mhz=gssi_converter.antenna_frequency_mhz(header),
            sample_interval_ns=axis["sample_interval_ns"], n_traces=int(n_traces),
            n_samples=header["n_samples"], license="CC-BY-4.0", commercial_use_permitted=True,
            license_pool=LicensePool.COMMERCIAL_COMPATIBLE,
            split=split_by_path[path], exposure=SiteExposure.UNSEEN_LABELS_SEEN_ACQUISITION,
        ))

    for path in rd3_paths:
        try:
            rad_path = mala_converter.find_rad(path)
            header = mala_converter.parse_rad(rad_path)
            axis = mala_converter.derive_time_axis(header, rad_path)
        except Exception:
            continue
        width = {".rd3": 2, ".rd7": 4}.get(path.suffix.lower(), 2)
        n_traces = path.stat().st_size // (axis["n_samples"] * width)
        if n_traces < 1:
            continue
        out.append(SSLSourceFile(
            dataset_id="tu1208-ifsttar", site_id="tu1208-ifsttar",
            survey_id=path.stem, source_file=str(path.relative_to(REPO_ROOT)), reader="mala_rd3",
            sensor_vendor="MALA", antenna_frequency_mhz=mala_converter.antenna_frequency_mhz(header),
            sample_interval_ns=axis["sample_interval_ns"], n_traces=int(n_traces),
            n_samples=axis["n_samples"], license="CC-BY-4.0", commercial_use_permitted=True,
            license_pool=LicensePool.COMMERCIAL_COMPATIBLE,
            split=split_by_path[path], exposure=SiteExposure.UNSEEN_LABELS_SEEN_ACQUISITION,
        ))
    return out


def discover_hillside_source_files(root: Path = HILLSIDE_ROOT) -> list[SSLSourceFile]:
    """Native MALA `.rd3` files. One real site (`lancaster`); file-level split."""
    out: list[SSLSourceFile] = []
    if not root.exists():
        return out
    rd3_paths = sorted(root.rglob("*.rd3"))
    split_by_path = _file_level_split(rd3_paths)
    for path in rd3_paths:
        try:
            rad_path = mala_converter.find_rad(path)
            header = mala_converter.parse_rad(rad_path)
            axis = mala_converter.derive_time_axis(header, rad_path)
        except Exception:
            continue
        n_traces = path.stat().st_size // (axis["n_samples"] * 2)
        if n_traces < 1:
            continue
        out.append(SSLSourceFile(
            dataset_id="hillside-lancaster", site_id="hillside-lancaster",
            survey_id=path.stem, source_file=str(path.relative_to(REPO_ROOT)), reader="mala_rd3",
            sensor_vendor="MALA", antenna_frequency_mhz=mala_converter.antenna_frequency_mhz(header),
            sample_interval_ns=axis["sample_interval_ns"], n_traces=int(n_traces),
            n_samples=axis["n_samples"], license="CC-BY-4.0", commercial_use_permitted=True,
            license_pool=LicensePool.COMMERCIAL_COMPATIBLE,
            split=split_by_path[path], exposure=SiteExposure.UNSEEN_LABELS_SEEN_ACQUISITION,
        ))
    return out


def discover_testum_source_files(root: Path = TESTUM_ROOT) -> list[SSLSourceFile]:
    """
    Native GSSI `.DZT` files. RESERVED in full (see `RESERVED_DATASETS`) --
    `split`/`exposure` are still recorded (as `RESERVED`/`UNSEEN_SITE`) so a
    caller never has to special-case this dataset to know its role.
    """
    out: list[SSLSourceFile] = []
    if not root.exists():
        return out
    for path in sorted(root.rglob("*.DZT")) + sorted(root.rglob("*.dzt")):
        try:
            header = gssi_converter.parse_dzt_header(path)
            axis = gssi_converter.derive_time_axis(header, path)
        except Exception:
            continue
        width = {16: 2, 8: 1, 32: 4}.get(header["bits"], 2)
        n_traces = (path.stat().st_size - header["data_offset"]) // (header["n_samples"] * width)
        if n_traces < 1:
            continue
        out.append(SSLSourceFile(
            dataset_id="testum", site_id="testum-wittstock",
            survey_id=path.stem, source_file=str(path.relative_to(REPO_ROOT)), reader="gssi_dzt",
            sensor_vendor="GSSI", antenna_frequency_mhz=gssi_converter.antenna_frequency_mhz(header),
            sample_interval_ns=axis["sample_interval_ns"], n_traces=int(n_traces),
            n_samples=header["n_samples"], license="CC-BY-4.0", commercial_use_permitted=True,
            license_pool=LicensePool.COMMERCIAL_COMPATIBLE,
            split=SiteSplit.RESERVED, exposure=SiteExposure.UNSEEN_SITE,
        ))
    return out


def discover_grimsel_source_files(root: Path = GRIMSEL_ROOT) -> list[SSLSourceFile]:
    """
    The real Grimsel AU-tunnel `.rd3` -- RESEARCH_ONLY pool (non-commercial
    licence, `docs/grimsel-deep-evidence-audit.md`). Discovered and typed
    like every other real file so a research-only experiment can use it
    explicitly; NEVER returned by `discover_source_files`'s default
    (commercial-compatible) corpus.
    """
    out: list[SSLSourceFile] = []
    rd3_path = root / "GPR_AU_N-to-S.rd3"
    if not rd3_path.exists():
        return out
    try:
        rad_path = mala_converter.find_rad(rd3_path)
        header = mala_converter.parse_rad(rad_path)
        axis = mala_converter.derive_time_axis(header, rad_path)
    except Exception:
        return out
    n_traces = rd3_path.stat().st_size // (axis["n_samples"] * 2)
    if n_traces < 1:
        return out
    out.append(SSLSourceFile(
        dataset_id="grimsel-au-tunnel", site_id="grimsel-au-tunnel",
        survey_id=rd3_path.stem, source_file=str(rd3_path.relative_to(REPO_ROOT)), reader="mala_rd3",
        sensor_vendor="MALA", antenna_frequency_mhz=mala_converter.antenna_frequency_mhz(header),
        sample_interval_ns=axis["sample_interval_ns"], n_traces=int(n_traces),
        n_samples=axis["n_samples"], license="In Copyright - NonCommercial (InC-NC)",
        commercial_use_permitted=False, license_pool=LicensePool.RESEARCH_ONLY,
        split=SiteSplit.TRAIN, exposure=SiteExposure.UNSEEN_LABELS_SEEN_ACQUISITION,
    ))
    return out


def discover_source_files(commercial_only: bool = True) -> list[SSLSourceFile]:
    """
    Every real source file this milestone found, across every discoverer
    above. `commercial_only=True` (the default, and what
    `build_window_index`'s default corpus uses) filters to
    `LicensePool.COMMERCIAL_COMPATIBLE` -- the primary V1 encoder's corpus.
    Pass `False` to see the full audit including `RESEARCH_ONLY` sources
    (Section 2's table).
    """
    all_files = (
        discover_bam_source_files() + discover_fourtu_source_files()
        + discover_tu1208_source_files() + discover_hillside_source_files()
        + discover_testum_source_files() + discover_grimsel_source_files()
    )
    if commercial_only:
        return [f for f in all_files if f.license_pool == LicensePool.COMMERCIAL_COMPATIBLE]
    return all_files


# ---------------------------------------------------------------------------
# window construction (Section 7) -- reproducible, non-overlapping, real
# ---------------------------------------------------------------------------

PREPROCESSING_VERSION = "ssl-v1-dewow-window64x128"


def build_window_index(
    source_files: list[SSLSourceFile], trace_window: int = 64, sample_window: int = 128,
) -> list[SSLWindowRef]:
    """
    Enumerates every WHOLE, non-overlapping (trace_window x sample_window)
    window that fits inside each real source file -- a partial remainder at
    a file's edge is dropped, never padded. `(64, 128)` is chosen so every
    dimension is divisible by 8 (three 2x poolings in the encoder tower,
    Section 9) and fits inside the smallest real file held (Hillside: 336
    samples/trace; TestUM: 67 traces/file -- both exceed one window).
    """
    out: list[SSLWindowRef] = []
    for sf in source_files:
        n_trace_windows = sf.n_traces // trace_window
        n_sample_windows = sf.n_samples // sample_window
        for tw in range(n_trace_windows):
            t0 = tw * trace_window
            for sw in range(n_sample_windows):
                s0 = sw * sample_window
                out.append(SSLWindowRef(
                    dataset_id=sf.dataset_id, site_id=sf.site_id, survey_id=sf.survey_id,
                    source_file=sf.source_file, reader=sf.reader,
                    trace_start=t0, trace_end=t0 + trace_window - 1,
                    sample_start=s0, sample_end=s0 + sample_window - 1,
                    line_index=sf.line_index, sensor_vendor=sf.sensor_vendor,
                    antenna_frequency_mhz=sf.antenna_frequency_mhz,
                    sample_interval_ns=sf.sample_interval_ns,
                    preprocessing_version=PREPROCESSING_VERSION,
                    license=sf.license, commercial_use_permitted=sf.commercial_use_permitted,
                    license_pool=sf.license_pool, split=sf.split, exposure=sf.exposure,
                ))
    return out


# ---------------------------------------------------------------------------
# raw window materialisation -- dispatches to the EXISTING converters' own
# low-level readers, never a re-implementation of any parser
# ---------------------------------------------------------------------------

@dataclass
class _BamVolumeCache:
    """
    Per-process cache, keyed by (specimen, scan_id): a BAM volume is ~330 MB
    and must be read once per real (specimen, scan_id) pair, not per window.
    Holds EVERY volume touched, not just the most recent one -- with a
    shuffled training order (real SGD practice, not a mistake to work
    around), consecutive windows routinely come from different scan_ids, and
    a single-entry cache would reload the same ~330 MB archive member on
    almost every window. Only 8 such volumes exist in the entire held corpus
    (`BAM_SPECIMENS` x `BAM_SCAN_IDS`), so an unbounded cache here is bounded
    in practice (~2.6 GB at worst, all 8 loaded).
    """
    volumes: dict = field(default_factory=dict)


_bam_cache = _BamVolumeCache()


def read_window(ref: SSLWindowRef, root_by_dataset: Optional[dict[str, Path]] = None) -> np.ndarray:
    """
    Materialises ONE window's real amplitude values, shape
    `(sample_window, trace_window)`, dispatching on `ref.reader`. Every
    branch calls an EXISTING `converters/`/`benchmark/` reader -- this
    function contains no parsing logic of its own.
    """
    if ref.reader == "segy_le":
        f = segy_endian.LittleEndianSegyFile(REPO_ROOT / ref.source_file)
        try:
            rows = [f.trace[i] for i in range(ref.trace_start, ref.trace_end + 1)]
        finally:
            f._fh.close()
        arr = np.array(rows, dtype=float)  # (n_traces, n_samples)
        return arr[:, ref.sample_start:ref.sample_end + 1].T

    if ref.reader == "gssi_dzt":
        path = REPO_ROOT / ref.source_file
        header = gssi_converter.parse_dzt_header(path)
        traces, _ = gssi_converter.read_dzt(path, header)
        arr = np.array(traces[ref.trace_start:ref.trace_end + 1], dtype=float)
        return arr[:, ref.sample_start:ref.sample_end + 1].T

    if ref.reader == "mala_rd3":
        path = REPO_ROOT / ref.source_file
        rad_path = mala_converter.find_rad(path)
        header = mala_converter.parse_rad(rad_path)
        axis = mala_converter.derive_time_axis(header, rad_path)
        traces, _ = mala_converter.read_rd3(path, axis["n_samples"])
        arr = np.array(traces[ref.trace_start:ref.trace_end + 1], dtype=float)
        return arr[:, ref.sample_start:ref.sample_end + 1].T

    if ref.reader == "bam_npy_yslice":
        from benchmark import bam_ingest

        specimen = ref.site_id.replace("bam-", "")
        key = (specimen, ref.survey_id)
        if key not in _bam_cache.volumes:
            scan = bam_ingest.load_scan(specimen, ref.survey_id, root=BAM_ROOT)
            _bam_cache.volumes[key] = bam_ingest.load_volume(scan, root=BAM_ROOT)
        # volume: (n_x, n_y, n_samples); one line = fixed Y, all X, all samples
        line = _bam_cache.volumes[key][:, ref.line_index, :]  # (n_x, n_samples)
        window = line[ref.trace_start:ref.trace_end + 1, ref.sample_start:ref.sample_end + 1]
        return window.T  # (sample_window, trace_window)

    raise ValueError(f"unknown reader {ref.reader!r}")


# ---------------------------------------------------------------------------
# corpus audit (Section 2's table, computed from real discovery, never hand-typed)
# ---------------------------------------------------------------------------

def audit_corpus() -> list[dict]:
    """
    One row per real dataset (Section 2's table), computed from
    `discover_source_files(commercial_only=False)` -- includes both pools,
    explicitly labelled, never silently combined.
    """
    all_files = discover_source_files(commercial_only=False)
    by_dataset: dict[str, list[SSLSourceFile]] = {}
    for f in all_files:
        by_dataset.setdefault(f.dataset_id, []).append(f)

    rows = []
    for dataset_id, files in sorted(by_dataset.items()):
        vendors = sorted({f.sensor_vendor for f in files if f.sensor_vendor})
        freqs = sorted({f.antenna_frequency_mhz for f in files if f.antenna_frequency_mhz})
        sites = sorted({f.site_id for f in files})
        rows.append({
            "dataset_id": dataset_id,
            "sites": sites,
            "vendors": vendors,
            "frequencies_mhz": freqs,
            "n_source_files_or_lines": len(files),
            "total_traces": sum(f.n_traces for f in files),
            "license": files[0].license,
            "license_pool": files[0].license_pool.value,
            "commercial_use_permitted": files[0].commercial_use_permitted,
        })
    return rows
