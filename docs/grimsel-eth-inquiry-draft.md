# Grimsel — draft inquiry to ETH Zurich / dataset authors

**Status: DRAFT ONLY. Not sent.** Prepared strictly from the completed
evidence audit (`docs/grimsel-deep-evidence-audit.md`,
`docs/grimsel-geological-model-file-audit.md`,
`docs/grimsel-position-zero-reconciliation.md`). Nothing here was inferred
beyond what those three documents already establish; no new evidence was
sought for this task.

Per the pattern already established for the 4TU correspondence
(`docs/4tu-author-letter-draft.md`): this is a prepared draft, ready for a
human operator to review, edit and send at their own discretion. Producing
it does not constitute contacting anyone.

---

## 1. Email subject

> Grimsel ISC GPR dataset — coordinate reference and use permissions for research benchmarking

## 2. Intended recipients

| Recipient | Role | Section(s) most relevant to them |
|---|---|---|
| **Joseph Doetsch** (ETH Zurich) | Contact person and data collector on the GPR/seismic dataset ([10.3929/ethz-b-000420930](https://doi.org/10.3929/ethz-b-000420930)) | A.1, A.2, A.3, B (all) |
| **Hannes Krietsch** (ILF Consulting Engineers; corresponding author, geological dataset) | Contact person on the geological dataset ([10.3929/ethz-b-000243199](https://doi.org/10.3929/ethz-b-000243199)) and lead author of the Scientific Data paper describing the shear-zone characterisation | A.4, A.5 |

Both are proposed as **To:** recipients on one email, since the questions
span both datasets and the two authors are closely connected co-authors on
the same body of work — splitting into two separate emails would fragment
a question set that genuinely needs both perspectives (e.g. A.5 needs the
geological author's shear-zone data and the GPR author's profile geometry
together).

**For section B specifically (licensing), consider also copying
`research-collection@library.ethz.ch`.** ETH's own Research Collection
terms of use state that the Library "forwards release applications to the
work's copyright holder" — meaning the Library is the institution's
designated channel for exactly this kind of permission question, and
looping them in may get a faster or more authoritative answer than relying
on the individual researchers alone, who may not be positioned to grant
institutional permissions.

## 3. Which questions are essential vs. optional

| # | Question | Essential / optional | Why |
|---|---|---|---|
| A.1 | Absolute Swiss-grid position of the GPR profile's start point | **Essential** | This is the single fact that would resolve the entire scientific blocker; nothing else in the audit closes it |
| A.2 | Whether the 49.03 m profile follows the AU tunnel, and its exact origin/orientation relative to it | **Essential** | Directly resolves the 4.4 m length discrepancy the audit found and left unresolved |
| A.3 | Whether an official station/coordinate reference connects the GPR profile to the tunnel/geological model | **Essential** | If yes, this may answer A.1–A.2 in one document reference rather than requiring a fresh measurement from the authors |
| A.4 | Vertical reference/datum for comparing the GPR profile with the geological model | Optional, but cheap to ask alongside the essential three | The audit already narrowed this to "plausible but unnamed"; a direct answer removes the last named-datum gap at no extra cost to the recipient |
| A.5 | Authoritative association between the GPR profile and the shear-zone geometry, including expected intersection position/depth and uncertainty | Optional here, essential before any actual validation is run | Not needed to resolve co-registration itself, but is the next question that would arise immediately after A.1–A.3 are answered, so worth asking in the same round-trip |
| B.1–B.4 | Permitted uses (benchmarking, processing by software with future commercial potential, publishing derived results, retaining derived outputs) | **Essential**, all four | These are the specific "other uses" the InC-NC rights statement reserves to the rights-holder; none is answerable from public material, and all four gate different parts of how Subterra could actually use a "yes" on the science |
| B.5 | Whether separate commercial-use permission can be granted if not already covered | **Essential** | Directly actionable — either unlocks a path or closes it, rather than leaving the question open-ended |

## 4. Final email body

---

**Subject:** Grimsel ISC GPR dataset — coordinate reference and use permissions for research benchmarking

Dear Dr. Doetsch, Dr. Krietsch,

We are working on Subterra, a subsurface data platform, and are evaluating
openly available ground-penetrating radar datasets that could serve as an
independent validation benchmark for testing whether our software's
reconstructed subsurface positions match physically known geometry.

In that context we have reviewed the Grimsel ISC datasets you published:
the GPR and seismic dataset (10.3929/ethz-b-000420930) and the
comprehensive geological dataset (10.3929/ethz-b-000243199), along with the
accompanying Solid Earth and Scientific Data papers. We downloaded and
inspected the openly licensed geological-model package directly, including
the tunnel-coordinate and borehole-collar files, and confirmed that it
places the borehole and shear-zone geometry in an absolute Swiss national
grid reference (origin at Easting 667400, Northing 158800, Elevation 1700).

What we were not able to establish from the public material is the GPR
profile's own absolute position in that same coordinate system. We looked
specifically at the `plot_GPR.m` visualization script and confirmed that
its placement of the radargram image uses fixed offset values chosen for
the figure's appearance, not a surveyed coordinate — so we did not treat
it as one. We also checked whether the AU gallery's internal geometry or
Figure 3a of the Solid Earth paper resolved this, and neither does: the
gallery measurement describes a different, smaller passage, and Figure 3a
is a schematic without coordinate annotations. Rather than estimate or
infer a position from these sources, we would like to ask you directly.

**A. Scientific / geospatial questions**

1. What is the absolute Swiss-grid position (Easting, Northing, Elevation)
   of the GPR profile's position zero / start point?
2. Is the 49.03 m GPR profile intended to run along the AU tunnel as
   documented in `AUTunnel.txt`? If so, what is its exact origin and
   orientation relative to that tunnel?
3. Is there an official coordinate or station reference that connects the
   GPR profile to the tunnel and geological model coordinate system?
4. What vertical reference or datum should be used when comparing the GPR
   profile's depth axis with the geological model's elevations?
5. Is there an authoritative way to associate the GPR profile with the
   independently mapped shear-zone geometry — specifically, the expected
   intersection position and depth, and any known positional uncertainty?

**B. Licensing / permission questions**

The GPR and seismic dataset is currently listed as "In Copyright —
Non-Commercial Use Permitted." We would like to confirm what use this
permits before proceeding further:

1. Would you permit use of the raw GPR data for research benchmarking of
   our software?
2. Would you permit processing the data through software that is under
   active development and may have future commercial applications?
3. Would you permit publication of derived numerical results — for
   example localisation errors, comparison figures, or reconstructed
   interpretations — without redistributing the raw GPR data itself?
4. Would derived results and code be permitted to be retained after the
   raw dataset is no longer stored locally?
5. If commercial use is not covered by the current terms, is separate
   permission available, and if so, how should we request it?

We are asking rather than assuming on all of the above, since we would
rather have your confirmation than build on a guess. Thank you for your
time, and for making this dataset available in the first place.

Best regards,
[sender name]

---

## Notes for whoever sends this

- **Fill in the sender name** before sending — left blank deliberately,
  matching the existing convention in `docs/4tu-author-letter-draft.md`.
- **Do not add the internal 78/100 score or "Category B" classification.**
  These are Subterra's own working notes, not something the recipients
  need or would find meaningful, and including them would look like
  presenting an internal grade rather than asking a genuine question.
- **Do not claim Grimsel is a ready or complete X/Y/Z benchmark anywhere
  in this email** — it deliberately never says so, consistent with the
  audit's own finding that it is not.
- If sending to Krietsch's ILF Consulting Engineers address, consider
  whether a brief acknowledgement that he has since moved from ETH is
  appropriate context, though the draft above does not assume anything
  about his current affiliation beyond the address itself.
