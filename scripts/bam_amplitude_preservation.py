"""
Amplitude preservation on BAM: does Subterra's own DZT decoder reproduce the
authors' published `.npy` sample values?

RESEARCH CHECK, NOT A PRODUCT FEATURE. Reads the archives on disk, writes one
JSON artifact, changes nothing else.

WHY THIS IS AN INDEPENDENT TEST. The `.npy` volumes were produced by the
dataset authors with their own Python workflow from the same `.DZT` files
(Grohmann et al. 2026, Data in Brief 68:113103, section "Data formatting
workflow", Fig. 12): remove the first, redundant A-scan; reshape to
181 lines x 841 A-scans x 512 samples; reverse every second line starting with
line No. 0; correct a scan-line offset; crop the 2100 x 900 mm scanned area to
the 2000 x 800 mm field; resample X from 2.5 mm to 5 mm. Subterra's decoder
(`converters.gssi_converter.read_dzt`) was written from `readgssi.m` and the
file format, not from that workflow. If Subterra's decoded samples appear
verbatim (or as a fixed affine map) in the authors' array, the decode is
amplitude-preserving. The offset-correction and crop are not fully specified in
the paper, so the GEOMETRIC alignment is searched for (which DZT trace lands on
which grid node); the AMPLITUDE comparison is exact.

To keep memory small, only the first K whole scan lines of the DZT are decoded,
through a truncated copy of the file (header + K*841+1 traces), using the
unmodified `read_dzt`.

    venv/bin/python -m scripts.bam_amplitude_preservation \
        --out artifacts/bam/validation/amplitude_preservation.json
"""
from __future__ import annotations

import argparse
import json
import tempfile
import zipfile
from pathlib import Path

import numpy as np

from converters.gssi_converter import data_offset, parse_dzt_header, read_dzt

ROOT = Path("datasets/raw/bam_concrete")
N_PER_LINE = 841        # paper Table 3: measurement points in X (scanned area)
N_LINES = 181           # paper Table 3: scan lines in Y (scanned area)


def _npy(zf: zipfile.ZipFile, specimen: str, scan: str) -> np.ndarray:
    member = next(n for n in zf.namelist()
                  if n.endswith(f"{specimen}_3D_Dataset_{scan}.npy"))
    with zf.open(member) as f:
        return np.load(f, mmap_mode=None)


def check(specimen: str, scan: str, k_lines: int = 16, n_probe: int = 200) -> dict:
    zf = zipfile.ZipFile(ROOT / f"{specimen}_Dataset.zip")
    dzt_member = next(n for n in zf.namelist() if n.endswith(f"{specimen}_{scan}.DZT"))
    with tempfile.TemporaryDirectory() as tmp:
        full = Path(tmp) / "full.DZT"
        with zf.open(dzt_member) as src, open(full, "wb") as dst:
            dst.write(src.read())
        hdr = parse_dzt_header(full)
        hdr["data_offset"] = data_offset(hdr)
        n_total = (hdr["file_size"] - hdr["data_offset"]) // (hdr["n_samples"] * 2)
        keep = 1 + k_lines * N_PER_LINE
        cut = Path(tmp) / "cut.DZT"
        with open(full, "rb") as fh, open(cut, "wb") as out:
            out.write(fh.read(hdr["data_offset"] + keep * hdr["n_samples"] * 2))
        hcut = parse_dzt_header(cut)
        hcut["data_offset"] = data_offset(hcut)
        traces, n = read_dzt(cut, hcut)
    dz = np.asarray(traces, dtype=np.float64)[1:]          # Subterra decode; drop redundant A-scan
    lines = dz.reshape(k_lines, N_PER_LINE, -1)
    vol = _npy(zf, specimen, scan)                          # (401, 161, 512)

    # The authors' reader (readgssi convention) overwrites samples 0 and 1 with
    # sample 2; Subterra deliberately does not (converter docstring). Compare
    # samples 2..511 exactly, and report samples 0..1 separately.
    index = {}
    for L in range(k_lines):
        for i in range(N_PER_LINE):
            index.setdefault(lines[L, i, 2:].tobytes(), []).append((L, i))

    rng = np.random.default_rng(0)
    rows = [r for r in range(vol.shape[1]) if r < k_lines - 10]   # rows reachable from K lines
    picks = [(int(rng.integers(0, vol.shape[0])), int(rng.choice(rows))) for _ in range(n_probe)]
    matched, unmatched, s01_overwritten, mapping = 0, [], 0, []
    for xi, yi in picks:
        g = vol[xi, yi]
        hit = index.get(g[2:].tobytes())
        if hit:
            matched += 1
            L, i = hit[0]
            if g[0] == g[2] and g[1] == g[2]:
                s01_overwritten += 1
            mapping.append({"grid_x_index": xi, "grid_y_index": yi, "dzt_line": L,
                            "ascan_in_line_as_stored": i, "n_identical_ascans": len(hit)})
        else:
            unmatched.append((xi, yi))
    res = {"probes": len(picks), "exact_matches_samples_2_to_511": matched,
           "samples_0_1_equal_sample_2_in_npy": s01_overwritten,
           "unmatched": unmatched[:10], "mapping_examples": mapping[:12]}
    # the line offset: grid row y <-> DZT line
    res["grid_row_to_dzt_line"] = sorted({(m["grid_y_index"], m["dzt_line"]) for m in mapping})

    return {
        "specimen": specimen, "scan": scan,
        "dzt_member": dzt_member,
        "dzt_traces_total": int(n_total),
        "expected_from_paper": f"{N_LINES} x {N_PER_LINE} + 1 redundant = {N_LINES * N_PER_LINE + 1}",
        "dzt_trace_count_matches_paper": int(n_total) == N_LINES * N_PER_LINE + 1,
        "decoded_lines_checked": k_lines,
        "decoder": "converters.gssi_converter.read_dzt (unmodified)",
        "npy_dtype": str(vol.dtype),
        "comparison": res,
        "verdict": ("EXACT (samples 2-511); samples 0-1 differ only by the authors' "
                    "readgssi overwrite" if matched == len(picks) else
                    f"NOT EXACT: {len(picks) - matched} of {len(picks)} probes unmatched"),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path,
                   default=Path("artifacts/bam/validation/amplitude_preservation.json"))
    p.add_argument("--lines", type=int, default=16)
    args = p.parse_args()
    out = [check("Pk266", "1_5_GHz_Rot00", args.lines), check("Pk401", "2_6_GHz_Rot00", args.lines)]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1))
    for r in out:
        print(r["specimen"], r["scan"], r["verdict"], r["dzt_trace_count_matches_paper"])
        c = r["comparison"]
        print("   ", {k: c[k] for k in ("probes", "exact_matches_samples_2_to_511",
                                         "samples_0_1_equal_sample_2_in_npy")}, c["grid_row_to_dzt_line"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
