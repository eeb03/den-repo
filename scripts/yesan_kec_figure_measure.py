"""
Measure buried-object positions and depths off the KEC testbed layout figures.

Source: Korea Expressway Corporation Research Institute report EXTRI-2018-40-534.9607
("포장하부 상태평가를 위한 비파괴 조사방안 연구", CODIL OTKCRK190187), Figures 4.5
(asphalt section), 4.7 (approach-slab section) and 4.10 (concrete section). The
figures are copyrighted and are NOT in git: they live in the git-ignored
`datasets/raw/references/kec_extri_2018_40/` (see docs/yesan-registration-investigation.md
for how they were obtained). This script only reads them.

What it measures, and what it cannot:

* Each figure is a schematic drawn on a 1 m grid: 0-30 m along the section, and two
  cross-sections (line A, line B) with gridlines every 0.5 m of depth below the
  pavement surface. The script finds the 0 m / 30 m gridlines and the depth
  gridlines in the image itself and converts pixel positions to metres.
* An object is a connected blob of one of the figure's legend colours. Its
  longitudinal position is the blob's horizontal centre; its depth is the blob's
  top edge (the figures draw each object's top at its burial depth -- e.g. the
  D1.0 hemisphere at 17 m in Fig. 4.5 tops out on the 3.0 m line, the maximum the
  report's Table 4.6 gives for D1.0 styrofoam).
* The figures are schematic: object sizes are not to scale, and the drawing
  precision is roughly one grid cell fraction. Read the outputs as figure
  readings (about +-0.1 m along the line, +-0.1-0.15 m in depth), never as
  as-built survey coordinates. The report states depth ranges per object type
  (Tables 4.6-4.8); per-object depths exist only in these drawings.
* It is an AID, not the transcription. The coloured classes (styrofoam, steel,
  earthenware, plastic containers) separate cleanly; the grey and black classes
  (concrete/asphalt blocks, rock) share colours with the pavement bars, hatching
  and text and are unreliable on their own. Every row of
  evidence/yesan/kec_testbed_targets.csv was checked by eye against the plan and
  the cross-section; that file, not this script's output, is the record.

Usage:  venv/bin/python scripts/yesan_kec_figure_measure.py [--json out.json]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

REF = Path(__file__).resolve().parents[1] / "datasets/raw/references/kec_extri_2018_40"

# Legend colours, sampled from Fig. 4.5 (RGB). Tolerances are per-channel.
COLOURS = {
    "styrofoam_hemisphere": (130, 190, 202),
    "steel_plate": (226, 64, 101),
    "earthenware_water": (159, 138, 193),
    "earthenware_air": (234, 145, 110),
    "plastic_container_water": (79, 154, 201),
    "plastic_container_air": (124, 175, 124),
    "asphalt_block": (66, 66, 66),
    "concrete_block": (114, 114, 114),
    "rock": (94, 99, 103),
}
TOL = 14

FIGURES = {
    "fig4.5": ("fig4.5_asphalt_layout.jpg", "asphalt"),
    "fig4.7": ("fig4.7_approach_slab_layout.jpg", "approach_slab"),
    "fig4.10": ("fig4.10_concrete_layout.jpg", "concrete"),
}


def _groups(idx, gap=2):
    out = []
    for i in idx:
        if out and i - out[-1][-1] <= gap:
            out[-1].append(i)
        else:
            out.append([i])
    return [float(np.mean(g)) for g in out]


def calibrate(grey):
    """Return x(0 m), px/m, and per-section (y of 0 m depth, px/m depth)."""
    h, w = grey.shape
    band = grey[int(h * 0.52):int(h * 0.68)]
    vlines = _groups([x for x in range(w) if (band[:, x] < 140).mean() > 0.35])
    # the regular 1 m grid: keep lines whose spacing to a neighbour is ~1/30 of the span
    x0, x30 = vlines[0], vlines[-1]
    pxm = (x30 - x0) / 30.0
    hl = _groups([y for y in range(h) if (grey[y] < 150).mean() > 0.45])
    # Depth gridlines: single-pixel rows every 0.5 m (~28 px). In each cross-section
    # the LAST such row is the 3.0 m line (true in all three figures); rows near the
    # surface can be hidden behind the drawn slab, so anchor on the bottom one.
    rows = [y for y in hl if y > h * 0.48]
    runs, cur = [], [rows[0]]
    for a, b in zip(rows, rows[1:]):
        if 24 <= b - a <= 33:
            cur.append(b)
        else:
            runs.append(cur)
            cur = [b]
    runs.append(cur)
    runs = [r for r in runs if len(r) >= 4][:2]
    sections = []
    for r in runs:
        step = float(np.median(np.diff(r)))           # px per 0.5 m
        sections.append({"y0": r[-1] - 6 * step, "px_per_m": step / 0.5, "rows": r})
    return x0, pxm, sections


def blobs(rgb, box):
    """Solid blobs of any legend colour, each classified by its mean colour."""
    from scipy import ndimage  # local import: only this script needs it
    x0, y0, x1, y1 = box
    sub = rgb[y0:y1, x0:x1].astype(int)
    pal = np.array(list(COLOURS.values()))
    dist = np.abs(sub[:, :, None, :] - pal[None, None, :, :]).max(axis=3)
    mask = dist.min(axis=2) <= TOL
    lab, _ = ndimage.label(mask)
    out = []
    names = list(COLOURS)
    for i, sl in enumerate(ndimage.find_objects(lab), start=1):
        ys, xs = sl
        own = lab[sl] == i
        size = int(own.sum())
        fill = size / own.size
        if size < 80 or fill < 0.6:          # text strokes, gridlines, hatching
            continue
        mean = sub[sl][own].mean(axis=0)
        cls = names[int(np.abs(pal - mean).max(axis=1).argmin())]
        out.append({"object_type": cls, "x_px": x0 + (xs.start + xs.stop - 1) / 2.0,
                    "top_px": y0 + ys.start, "w_px": xs.stop - xs.start, "n_px": size,
                    "fill": round(fill, 2)})
    return out


def measure(fig_key):
    fn, section = FIGURES[fig_key]
    img = Image.open(REF / fn).convert("RGB")
    rgb = np.asarray(img)
    grey = np.asarray(img.convert("L")).astype(int)
    x0, pxm, secs = calibrate(grey)
    out = {"figure": fig_key, "file": fn, "section": section, "x0_px": x0, "px_per_m": pxm,
           "depth_sections": [{k: v for k, v in s.items() if k != "rows"} for s in secs],
           "objects": []}
    for line, sec in zip(("A", "B"), secs):
        top = int(sec["y0"] - 4)
        bottom = int(sec["y0"] + 3.25 * sec["px_per_m"])
        for b in blobs(rgb, (int(x0) + 1, top, int(x0 + 30 * pxm), bottom)):
            if b["w_px"] > 3 * pxm:           # a drawn slab or zone, not an object
                continue
            out["objects"].append({
                "line": line, "object_type": b["object_type"],
                "position_m": round((b["x_px"] - x0) / pxm, 2),
                "top_depth_m": round((b["top_px"] - sec["y0"]) / sec["px_per_m"], 2),
                "drawn_width_m": round(b["w_px"] / pxm, 2), "n_px": b["n_px"]})
    out["objects"].sort(key=lambda o: (o["line"], o["position_m"]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    args = ap.parse_args()
    res = [measure(k) for k in FIGURES]
    for r in res:
        print(f"== {r['figure']} ({r['section']}): x0={r['x0_px']:.1f}px, {r['px_per_m']:.2f}px/m, "
              f"depth sections {[(round(s['y0'],1), round(s['px_per_m'],1)) for s in r['depth_sections']]}")
        for o in r["objects"]:
            print(f"  {o['line']} {o['position_m']:6.2f} m  top {o['top_depth_m']:5.2f} m  "
                  f"{o['object_type']:<24} w={o['drawn_width_m']:.2f} n={o['n_px']}")
    if args.json:
        Path(args.json).write_text(json.dumps(res, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
