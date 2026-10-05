"""
Register a BAM scan as a gridded product dataset, and print the calibration
picks a user would declare for it.

    python -m scripts.register_bam_volume_dataset --specimen Pk266 --scan 1_5_GHz_Rot00 \
        --owner-email you@example.com

The dataset carries NO calibration: the printed points (back-wall reflection
times picked by the pre-registered rule of scripts/bam_quantitative_validation,
depths from the fabrication drawings) are for the user to declare through the
normal `depth_calibration` declaration, together with the antenna offset. The
targets are never read here except to EXCLUDE object windows from the
back-wall picks, which is the existing rule.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def calibration_lines(specimen: str, scan: str, root: Path) -> list[str]:
    from benchmark.bam_ingest import load_scan, load_volume
    from scripts.bam_quantitative_validation import (
        STEP_THICKNESS_MM, backwall_candidates, load_gt, select_backwall,
    )
    s = load_scan(specimen, f"{specimen}_3D_Dataset_{scan}", root)
    vol = load_volume(s, root)
    targets, boreholes = load_gt()
    bh = [b for b in boreholes if b["id"].startswith(specimen)]
    sel = select_backwall(backwall_candidates(vol, s.grid, float(s.grid.z[1] - s.grid.z[0]),
                                              targets.get(specimen, []), bh), STEP_THICKNESS_MM[specimen])
    if sel["as_drawn"] is None:
        return []
    out = []
    for k, t in enumerate(sel["as_drawn"]["times"]):
        d = STEP_THICKNESS_MM[specimen][k]
        out.append(f"{d / 1000:.4f}, {t:.4f}, fabrication_drawing, "
                   f"Grohmann et al. 2026 drawings back-wall step {k} thickness {d} mm, {specimen}-backwall-{k}")
    return out


def main() -> int:
    from database.models import User
    from database.session import SessionLocal, init_db
    from ingestion.bam_grid import register_bam_scan

    ap = argparse.ArgumentParser()
    ap.add_argument("--specimen", default="Pk266")
    ap.add_argument("--scan", default="1_5_GHz_Rot00")
    ap.add_argument("--owner-email")
    ap.add_argument("--root", type=Path, default=Path("datasets/raw/bam_concrete").resolve())
    args = ap.parse_args()
    init_db()
    with SessionLocal() as db:
        owner = None
        if args.owner_email:
            u = db.query(User).filter(User.email == args.owner_email).first()
            if u is None:
                raise SystemExit(f"no user {args.owner_email}")
            owner = u.id
        ds = register_bam_scan(db, owner, args.specimen, args.scan, root=args.root)
    print("dataset_id", ds)
    print("calibration points (depth_m, time_ns, depth_source, depth_evidence, reflector_id):")
    for line in calibration_lines(args.specimen, args.scan, args.root):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
