"""Inspect the BAM concrete GPR archives without unpacking 2.5 GB to disk.

Answers, from the files themselves rather than from the publisher's prose:
  * does the published MD5 match what we downloaded?
  * what are the trace coordinate vectors, and what are their units and step?
  * does the CSV agree with the DZT on the number of traces and samples?
  * does Subterra's existing GSSI reader open these files unmodified?

Run:  python scripts/inspect_bam_concrete.py datasets/raw/bam_concrete
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

import numpy as np

# Published by Harvard Dataverse for doi:10.7910/DVN/FCMUJQ.
PUBLISHED_MD5 = {
    "Pk050_Dataset.zip": "433018325dc1b39a2924a8bf3211ed49",
    "Pk266_Dataset.zip": "e43ea0991a1e7b842d4e20d89b0b30f7",
    "Pk401_Dataset.zip": "b5262d4ea98dd0a9a40941aef9bec5e9",
}


def md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def describe_vector(zf: zipfile.ZipFile, name: str) -> dict:
    arr = np.load(io.BytesIO(zf.read(name)))
    steps = np.diff(arr)
    return {
        "name": name.split("/")[-1],
        "dtype": str(arr.dtype),
        "n": int(arr.size),
        "first": float(arr[0]),
        "last": float(arr[-1]),
        "step": float(steps[0]) if steps.size else None,
        "step_is_uniform": bool(np.allclose(steps, steps[0])) if steps.size else None,
    }


def inspect(archive: Path) -> dict:
    out: dict = {"archive": archive.name, "bytes": archive.stat().st_size}

    digest = md5(archive)
    expected = PUBLISHED_MD5.get(archive.name)
    out["md5"] = digest
    out["md5_published"] = expected
    out["md5_matches"] = (digest == expected) if expected else None

    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        out["members"] = len(names)

        out["coordinate_vectors"] = [
            describe_vector(zf, n) for n in sorted(names)
            if n.endswith(("X-values.npy", "Y-values.npy", "Z-values.npy"))
        ]

        # One CSV line: how are traces and samples laid out?
        csvs = sorted(n for n in names if n.endswith(".csv"))
        out["csv_count"] = len(csvs)
        if csvs:
            raw = zf.read(csvs[0]).decode("utf-8", "replace").splitlines()
            cells = [len(r.split(",")) for r in raw[:5]]
            out["csv_sample"] = {
                "name": csvs[0].split("/")[-1],
                "rows": len(raw),
                "cells_per_row_first5": cells,
                "first_row_head": raw[0][:120],
            }

        dzts = sorted(n for n in names if n.upper().endswith(".DZT"))
        out["dzt_count"] = len(dzts)
        out["dzt_names"] = [n.split("/")[-1] for n in dzts]
        if dzts:
            out["dzt_probe"] = probe_dzt(zf, dzts[0])
    return out


def probe_dzt(zf: zipfile.ZipFile, name: str) -> dict:
    """Open the DZT with Subterra's existing reader -- no new parsing here.

    Only the leading bytes are staged, which is enough for the header; the
    point is whether the existing GSSI path recognises the file at all.
    """
    import tempfile

    from converters.gssi_converter import antenna_frequency_mhz, parse_dzt_header

    with zf.open(name) as src, tempfile.NamedTemporaryFile(suffix=".DZT") as tmp:
        tmp.write(src.read(1 << 20))
        tmp.flush()
        try:
            hdr = parse_dzt_header(tmp.name)
        except Exception as exc:                 # reported, never swallowed
            return {"name": name.split("/")[-1], "error": f"{type(exc).__name__}: {exc}"}

    return {
        "name": name.split("/")[-1],
        "read_by": "converters.gssi_converter.parse_dzt_header",
        "antenna_frequency_mhz": antenna_frequency_mhz(hdr),
        "header": {k: v for k, v in sorted(hdr.items())
                   if isinstance(v, (int, float, str, bool, type(None)))},
    }


def main(argv: list[str]) -> int:
    root = Path(argv[1] if len(argv) > 1 else "datasets/raw/bam_concrete")
    archives = sorted(root.glob("*.zip"))
    if not archives:
        print(f"no archives under {root}", file=sys.stderr)
        return 1
    report = [inspect(a) for a in archives]
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
