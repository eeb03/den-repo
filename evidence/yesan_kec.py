"""
The Yesan test site as CONSTRUCTED, from the Korea Expressway Corporation's design report.

SOURCE. Korea Expressway Corporation Research Institute, "포장하부 상태평가를 위한 비파괴
조사방안 연구" (A study on non-destructive survey methods for assessing conditions under
pavement), report EXTRI-2018-40-534.9607, 216 pp., public PDF at CODIL (Korea's
construction-technology library), record OTKCRK190187. The PDF, its extracted text and its
figures are copyrighted and are NOT in git: they are held in the git-ignored
`datasets/raw/references/kec_extri_2018_40/`. Only Subterra's own transcription is here:

    evidence/yesan/kec_tables_4_6_to_4_8.csv   Tables 4.6-4.8, cell by cell
    evidence/yesan/kec_testbed_targets.csv     one row per drawn object (Figs. 4.5, 4.7, 4.10)
    evidence/yesan/rhee2021_vs_kec_comparison.csv
                                               the same objects read off Rhee et al. (2021)
                                               Fig. 3, with every disagreement kept

TWO KINDS OF FACT, KEPT APART. The report describes (a) the testbed that was built --
where each object is, what it is, how deep -- and (b) four MALA survey campaigns run on
it in 2017-18. The radar files Subterra holds (Zenodo 21441974) are a DIFFERENT, later
survey (2021-04-06). So (a) is authoritative ground truth for the site, and (b) is at
most supporting context for processing the 2021 files: a time-zero shift or a migration
velocity chosen for a 2017-18 survey was never measured on the 2021 data and must not be
applied to it as if it were. `SUPPORTING_ONLY` records (b) with `transferable_to_2021`
False on every entry.

WHAT THIS DOES NOT DO. It does not register the 2021 traces to the testbed. Knowing where
the targets are is not the same as knowing which trace is above which target; that needs
the 2021 survey direction, its start alignment and the meaning of the authors' 27 m /
3116-interval distance calibration (`REGISTRATION_STATUS`), none of which the report can
supply because it predates the survey.
"""
from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent / "yesan"
TABLES_CSV = HERE / "kec_tables_4_6_to_4_8.csv"
TARGETS_CSV = HERE / "kec_testbed_targets.csv"
COMPARISON_CSV = HERE / "rhee2021_vs_kec_comparison.csv"

KEC_REPORT = {
    "id": "KEC EXTRI-2018-40-534.9607",
    "title_ko": "포장하부 상태평가를 위한 비파괴 조사방안 연구",
    "title_en": "A study on non-destructive survey methods for assessing conditions under pavement",
    "publisher": "Korea Expressway Corporation Research Institute",
    "url": "https://www.codil.or.kr/filebank/original/RK/OTKCRK190187/OTKCRK190187.pdf",
    "pages": 216,
    "held_at": "datasets/raw/references/kec_extri_2018_40/ (git-ignored, not redistributed)",
    "obtained": "2026-10-05, by direct download from CODIL",
}
RHEE_2021 = {
    "id": "Rhee et al. 2021",
    "citation": ("Rhee, J.Y.; Park, K.T.; Cho, J.W.; Lee, S.Y. A Study of the Application and "
                 "the Limitations of GPR Investigation on Underground Survey of the Korean "
                 "Expressways. Remote Sens. 2021, 13, 1805"),
    "doi": "10.3390/rs13091805",
    "figure": "Figure 3 (full resolution 3062x4063 PNG from the MDPI CDN)",
    "held_at": "datasets/raw/references/rhee2021_fig3_fullres.png (git-ignored)",
}

#: Section order and lengths, Fig. 4.3 (PDF p. 82, printed p. 60): asphalt 30 m, approach
#: slab 30 m, concrete 30 m, contiguous. Testbed chainage = offset + position in section.
SECTIONS = {"asphalt": 0.0, "approach_slab": 30.0, "concrete": 60.0}
SECTION_LENGTH_M = 30.0

#: The `00000IC` road-performance test site the report names (PDF p. 91) is anonymised.
SITE_NAMED_IN_REPORT = "00000IC road-performance test site (anonymised in the report)"


@dataclass(frozen=True)
class Fact:
    """One statement from the report, with where it is and what it is evidence for."""
    id: str
    statement: str
    where: str
    classification: str  # "authoritative_testbed" | "supporting_only_2021" | "inferred"
    transferable_to_2021: bool = False
    note: str = ""


#: The constructed site. Authoritative for the TESTBED; none of it is a 2021 registration.
TESTBED_FACTS: tuple[Fact, ...] = (
    Fact("line-geometry",
         "Buried objects lie on two survey lines 1.5 m either side of the road centreline: "
         "line A on the left, line B on the right.",
         "§4.3.3, PDF p. 82 (printed p. 60); Fig. 4.3", "authoritative_testbed"),
    Fact("line-a-cavity-models-only",
         "Line A carries only cavity models: styrofoam hemispheres (asphalt, approach-slab "
         "and concrete sections) and, at the abutment, two real voids formed from square "
         "styrofoam that was dug out after the approach slab was built, each with a "
         "locator steel plate inside.",
         "§4.3.3.1-4.3.3.3, PDF pp. 83, 85, 86 (printed 61, 63, 64); Figs. 4.5, 4.7, 4.10",
         "authoritative_testbed",
         note="two concrete-section D0.5 hemispheres are drawn ~0.4-0.45 m outside line A"),
    Fact("line-b-other-objects",
         "Line B carries every other object type: steel plates, plastic containers (water / "
         "empty), styrofoam, asphalt and concrete blocks, rock, earthenware (water / empty), "
         "loosened-ground zones.",
         "§4.3.3.1-4.3.3.3, PDF pp. 84-86; Figs. 4.5, 4.7, 4.10", "authoritative_testbed",
         note=("several 0.5x1.0 m objects and the empty earthenware are drawn between the "
               "centreline and line B, not on it -- see lateral_placement")),
    Fact("start-steel-plate",
         "A steel plate was installed where the asphalt section begins 'to mark the survey "
         "start point' (아스콘포장 구간이 시작되는 시점에는 강판을 설치하여 조사 시점을 나타내었다).",
         "§4.3.3.1, PDF p. 84 (printed p. 62); drawn on line B at 0.0-0.5 m in Fig. 4.5 "
         "(PDF p. 83); 0.5x0.5x0.1 m at 0.27 m depth, Table 4.6",
         "authoritative_testbed",
         note=("on line B only -- no plate is drawn at the start of line A; and it is buried "
               "0.27 m deep, so it is not a mark a 2021 operator could see on the surface")),
    Fact("end-steel-plate",
         "A steel plate was installed where the concrete section ends (콘크리트 포장구간이 "
         "끝나는 종점에는 강판을 설치하여 조사 시점을 나타내었다).",
         "§4.3.3.3, PDF p. 86 (printed p. 64); drawn on line B at 29.5-30.0 m of the concrete "
         "section in Fig. 4.10; 0.5x0.5x0.1 m at 0.45 m, Table 4.8",
         "authoritative_testbed"),
    Fact("longitudinal-structure",
         "The road part of the testbed is 90 m: asphalt 0-30 m, approach slab 30-60 m, "
         "concrete 60-90 m (plain concrete 60-75 m, CRCP 75-90 m).",
         "Fig. 4.3, PDF p. 82; plain/CRCP split: PDF p. 134 (printed 112) and Fig. 4.10 shading",
         "authoritative_testbed"),
    Fact("abutment",
         "The bridge abutment is at the middle of the approach-slab section: stem at "
         "14.7-15.3 m and footing at 14.0-16.0 m of that section (testbed 44.7-45.3 m and "
         "44.0-46.0 m). The asphalt-side approach slab runs 9.0 m to it (36-45 m); the "
         "concrete side has an 8.75 m approach slab and a 6.0 m buffer slab (45-60 m).",
         "§4.3.3.2, PDF p. 84 (printed p. 62); Fig. 4.7, PDF p. 85", "authoritative_testbed",
         note="positions read from Fig. 4.7, +-0.1 m"),
    Fact("object-positions-surveyed-by-gps",
         "Each object's plan position was measured with GPS coordinates during installation.",
         "Table 4.22, PDF p. 98 (printed p. 76)", "authoritative_testbed",
         note="the coordinates themselves are not published; positions here are read off "
              "the design figures"),
    Fact("depth-reference",
         "Depths are below the pavement surface: the shallowest cavity model sits 'directly "
         "beneath the pavement' at 0.27 m (the asphalt layers are 5+7+15 = 27 cm); the "
         "concrete minimum, 0.45 m, is the 30 cm slab + 15 cm lean base.",
         "PDF p. 113 (printed p. 91); Tables 4.6, 4.8; §4.3.3.1, §4.3.3.3",
         "authoritative_testbed",
         note=("Rhee et al. 2021 states that the EPS depths are to the TOP surface; for "
               "other object types the point of the object a depth refers to is not stated")),
    Fact("groundwater",
         "Groundwater stands at 3.0 m, at the embankment / original-ground boundary.",
         "PDF p. 139 (printed p. 117)", "authoritative_testbed"),
)

#: The 2017-18 KEC surveys. NOT measured on the 2021 files. Context only.
SUPPORTING_ONLY: tuple[Fact, ...] = (
    Fact("kec-survey-campaigns",
         "Four single-channel MALA ProEx campaigns: 2017-06-09/15 (before paving), "
         "2017-09-20/23 (just after), 2018-04-25/27 (after winter), 2018-08-06/08 (age 1 yr).",
         "Tables 5.1-5.2, PDF pp. 109-110 (printed 87-88)", "supporting_only_2021"),
    Fact("kec-antenna-separation",
         "Transmitter-receiver separation 0.5 m (100 MHz), 0.36 m (250 MHz), 0.18 m (500 MHz).",
         "Table 5.3, PDF p. 111 (printed p. 89)", "supporting_only_2021",
         note=("the 2021 .rad headers all read ANTENNA SEPARATION 0.18 regardless of folder; "
               "whether that is true for the 250/800 MHz runs is itself an open question")),
    Fact("kec-time-zero",
         "Time-zero correction applied as a time-muting offset of -(antenna separation)/c, "
         "e.g. -0.36/3E8 s (~1.2 ns) for 250 MHz.",
         "Table 5.4, PDF p. 112 (printed p. 90)", "supporting_only_2021",
         note="a processing choice for the 2017-18 data, not a measured 2021 time zero"),
    Fact("kec-migration-velocity",
         "Kirchhoff migration velocity 0.75E+8 m/s (0.075 m/ns).",
         "Table 5.4, PDF p. 112", "supporting_only_2021",
         note="a processing parameter, not a velocity measurement on the 2021 survey"),
    Fact("kec-acquisition-settings",
         "Trace interval 0.05 m (0.02 m in campaign 2), time windows 60.1-61.5 ns "
         "(120.1 ns for 100 MHz in campaign 4), 230-898 samples, stacks 4-16, Reflex-W "
         "processing.",
         "Table 5.3, PDF p. 111", "supporting_only_2021"),
)


@dataclass(frozen=True)
class RegistrationComponent:
    component: str
    status: str  # SOLVED FOR TESTBED | SOLVED FOR 2021 SURVEY | PARTIALLY SOLVED | STILL UNKNOWN
    basis: str


REGISTRATION_STATUS: tuple[RegistrationComponent, ...] = (
    RegistrationComponent(
        "physical testbed 0 m reference", "SOLVED FOR TESTBED",
        "steel plate at the start of the asphalt section, line B, 0.0-0.5 m, 0.27 m deep "
        "(KEC PDF pp. 83-84). It defines the testbed origin; it does NOT show that trace 0, "
        "or the authors' 2021 '0 m' trace, is above it -- and line A has no such plate."),
    RegistrationComponent(
        "constructed target coordinates / distances", "SOLVED FOR TESTBED",
        "Tables 4.6-4.8 give type, size, count and depth (single value or range); Figs. "
        "4.5/4.7/4.10 give each object's position (read +-0.1 m). Counts reconcile exactly "
        "for asphalt (40) and concrete (42); the approach-slab section does not (drawn 34, "
        "table rows 36, text 38)."),
    RegistrationComponent(
        "line A / line B geometry", "SOLVED FOR TESTBED",
        "+-1.5 m from the centreline, A left, B right (KEC PDF p. 82)."),
    RegistrationComponent(
        "KEC testbed is the Zenodo 21441974 site", "PARTIALLY SOLVED",
        "inferred, strongly: same operator (KEC Research Institute), same 90 m asphalt / "
        "approach-slab / concrete bridge-transition layout, QDM file names using exactly the "
        "KEC section chainages (approach slab 30-60, plain 60-74, reinforced 75-90), and "
        "2021 radar changes at the KEC landmarks. No held source states it; the report "
        "anonymises the site."),
    RegistrationComponent(
        "2021 survey direction", "PARTIALLY SOLVED",
        "inferred: the 2021 near-surface changes at 44.0-45.0, ~60 and 72.6-75.6 m coincide "
        "with the abutment (44-46 m), the approach-slab / concrete boundary (60 m) and the "
        "plain / CRCP boundary (75 m) only if both lines start at the asphalt end. Not "
        "declared by the authors; POSITIVE DIRECTION -1 is an instrument setting."),
    RegistrationComponent(
        "2021 trace-to-distance scale", "STILL UNKNOWN",
        "two scales: the .rad wheel 0.008429 m/trace and the authors' sheet 27/3116 = "
        "0.0086649550706 m/trace (2.8% longer). Which one maps to testbed metres is unknown."),
    RegistrationComponent(
        "meaning of the 27 m / 3116-interval calibration", "STILL UNKNOWN",
        "the KEC report describes a 90 m site in three 30 m sections and contains no 27 m "
        "calibration distance; it predates the 2021 survey and cannot explain it."),
    RegistrationComponent(
        "whether 2021 target positions are expected in the same distance frame",
        "STILL UNKNOWN",
        "no 2021 target list is held; whether the dataset's own target table (MDPI Sensors) "
        "uses KEC design chainage, the sheet distance or the wheel distance is unstated."),
    RegistrationComponent(
        "exact 2021 trace-to-testbed transformation", "STILL UNKNOWN",
        "needs direction, start alignment (which trace is above testbed 0 m on each line) "
        "and the scale. The landmark coincidences are consistent with sheet 0 m ~ testbed "
        "0 m but are NOT used as a registration: fitting radar features to design landmarks "
        "would make the radar define its own truth frame."),
)

AUTHOR_QUESTIONS: tuple[str, ...] = (
    "Is the Zenodo 21441974 site the KEC road-performance-test-site testbed of report "
    "EXTRI-2018-40-534.9607 / Rhee et al. 2021, and were any buried objects added, removed "
    "or moved between 2018 and the 2021-04-06 survey?",
    "On each 2021 line, what physical mark is the '0 m' (zero-position traces 65/96/107 on A, "
    "80/60/60 on B)? Is it the asphalt-section start steel plate (line B), and what was used "
    "on line A, which has no plate?",
    "Were both 2021 lines run from the asphalt end toward the concrete end?",
    "What was the 27 m reference distance behind dx = 27/3116 = 0.0086649550706 m (where was "
    "it measured, on which line, and is it a tape measurement between surface marks)?",
    "Are the target positions in the dataset's MDPI Sensors table KEC design chainage "
    "(asphalt start = 0 m), the sheet distance (trace - zero trace) x dx, or the wheel distance?",
    "Are KEC Figs. 4.5/4.7/4.10 or Rhee 2021 Fig. 3 the as-built positions where they differ "
    "(e.g. concrete drain pipe at 4.6 vs 5.0 m; concrete line-A depths ~0.2-0.4 m apart)?",
)


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------

def _read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_tables() -> list[dict]:
    return _read(TABLES_CSV)


def load_targets() -> list[dict]:
    return _read(TARGETS_CSV)


def load_comparison() -> list[dict]:
    return _read(COMPARISON_CSV)


#: Totals stated in the report text for each section.
STATED_TOTALS = {"asphalt": 40, "approach_slab": 38, "concrete": 42}


def reconciliation() -> dict:
    """Per section: stated total, table-row sum, drawn items, and per-type differences."""
    tables, targets = load_tables(), load_targets()
    out = {}
    for sec in SECTIONS:
        table_types = Counter()
        for r in tables:
            if r["section"] == sec:
                table_types[r["object_type"]] += int(r["count"])
        drawn_types = Counter()
        for r in targets:
            if r["section"] == sec:
                drawn_types[r["object_type"]] += int(r["n_items"])
        diff = {k: (table_types[k], drawn_types[k])
                for k in set(table_types) | set(drawn_types) if table_types[k] != drawn_types[k]}
        out[sec] = {"stated_total": STATED_TOTALS[sec], "table_row_sum": sum(table_types.values()),
                    "drawn": sum(drawn_types.values()), "type_differences": diff}
    return out


# ---------------------------------------------------------------------------
# manifest targets
# ---------------------------------------------------------------------------

_DEPTH_METHOD = {"kec_text": "construction_record", "kec_table_single_value": "construction_record",
                 "kec_figure_reading": "publication_transcription"}


def _dimensions(size: str) -> dict:
    if size.startswith("D"):
        return {"units": "m", "outer_diameter": float(size[1:])}
    a, b, c = (float(x) for x in size.split("x"))
    return {"units": "m", "length": a, "width": b, "height": c,
            "note": "KEC table size; orientation (which side runs along the line) not stated"}


def manifest_targets() -> list[dict]:
    """The KEC objects as `subterra.targets.v1` targets in the testbed frames."""
    out = []
    for r in load_targets():
        lines = r["line"].split(";")
        locs = []
        for ln in lines:
            frame = f"yesan:testbed-{ln}"
            if r["extent_start_m"]:
                locs.append({"frame_id": frame, "geometry": "segment",
                             "start": [float(r["extent_start_m"])],
                             "end": [float(r["extent_end_m"])],
                             "uncertainty": float(r["position_uncertainty_m"]),
                             "note": "longitudinal extent read from the KEC figure"})
            else:
                locs.append({"frame_id": frame, "geometry": "point",
                             "coordinates": [float(r["testbed_position_m"])],
                             "uncertainty": float(r["position_uncertainty_m"]),
                             "note": (f"{r['section']} section position "
                                      f"{r['section_position_m']} m + {SECTIONS[r['section']]:g} m; "
                                      f"read from KEC Fig. {r['source_figure']}")})
        measured_to = r["depth_measured_to"]
        depth = {"value": float(r["depth_m"]), "units": "m", "measured_to": measured_to,
                 "reference_surface": "pavement_surface",
                 "method": _DEPTH_METHOD[r["depth_basis"]],
                 "uncertainty": 0.0 if r["depth_basis"] != "kec_figure_reading" else 0.15,
                 "source": (f"KEC EXTRI-2018-40-534.9607 Table {r['source_table']} "
                            f"(range {r['table_depth_range_m']} m) / Fig. {r['source_figure']}; "
                            f"basis {r['depth_basis']}")}
        if measured_to == "unresolved":
            depth["open_question"] = "yesan-depth-point"
        if r["depth_basis"] != "kec_figure_reading":
            depth.pop("uncertainty")
        out.append({
            "target_id": f"kec-{r['target_id']}",
            "object_class": r["object_type"],
            "line_id": None if len(lines) > 1 else lines[0],
            "dimensions": _dimensions(r["size_m"]),
            "locations": locs,
            "depths": [depth],
            "evidence": {
                "basis": "construction_record",
                "grade": "measurement_associated",
                "independent_of_gpr": True,
                "source": (f"KEC EXTRI-2018-40-534.9607, Table {r['source_table']} "
                           f"(PDF p. {r['source_pdf_page']}, printed p. {r['source_printed_page']}) "
                           f"and Fig. {r['source_figure']}"),
                "established_by": "Korea Expressway Corporation Research Institute (testbed builder)",
                "notes": ("constructed-testbed truth. Grade B, not A: the position is read off a "
                          "schematic design figure (the GPS installation coordinates are not "
                          "published), and the object's state at the 2021 survey is not "
                          "re-verified. Says nothing about which 2021 trace is above it."),
                "uncertainty": (f"position +-{r['position_uncertainty_m']} m (figure reading); "
                                f"depth basis {r['depth_basis']}"),
                "verified_by_subterra": False,
            },
            "notes": "; ".join(x for x in (
                f"n_items={r['n_items']}" if r["n_items"] != "1" else "",
                f"lateral: {r['lateral_placement']}",
                r["notes"]) if x),
        })
    return out
