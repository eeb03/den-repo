# 4TU author evidence — Dr. ter Huurne

> **Correction, 2026-08-15.** §1's table and §4's summary below were written
> before the header-field question (row 2 of the table: "Which header field
> holds it?") was resolved. It no longer needs an author answer: comparison
> against AHN across 366,019 traces in 107 activities identified SEG-Y bytes
> 45–48 as the ellipsoidal field (geoid-correlated separation from bytes
> 41–44, matching the published NL range) — see
> [`4tu-elevation-field-identification.md`](4tu-elevation-field-identification.md)
> and `evidence/fourtu_author.py`'s `OPEN_QUESTIONS[0].status`. The original
> table rows are left as written below, as the record of what was known at
> the time; §5 is rewritten to reflect the current state and does not repeat
> this stale framing.

The first external evidence request in this project to produce an answer. It
resolves a question that had been blocked for several stages, and it does not
unblock physical depth. Both halves matter.

**Authority:** Dr. ter Huurne, author of the 4TU dataset and accompanying paper.
**Channel:** direct written response to a Subterra enquiry.
**Verified by Subterra:** no. Nothing below has been checked against an
independent source, and none of it is a Subterra measurement.

The response is stored verbatim in `evidence/fourtu_author.py` so every claim
here can be checked against the words it was drawn from.

## 1. The evidence table

| Question | Author evidence | File evidence | Current state | Legitimate next state |
|---|---|---|---|---|
| What datum are the GNSS elevations on? | **WGS84 ellipsoidal, not NAP** | two per-trace elevation fields, both populated on 314/314 traces | `acquisition_elevation_datum: "UNDECLARED"` | datum **known**; the field was identified by measurement and the datum is now declared — see `docs/4tu-vertical-datum.md` |
| Which header field holds it? | *not stated* | bytes 41–44 ≈ 28.4 m, bytes 45–48 ≈ 72.35 m | both stored, neither named | **still unknown** — needs one more answer |
| Was the GNSS antenna height handled? | **yes, constant, already accounted for during acquisition** | — | unknown | **resolved** (for the GNSS rover only) |
| Does the GPR depth axis start at the ground? | **no — no time-zero correction, no air-gap removal, air path remains** | — | assumed not to | **confirmed not to**, magnitude still unknown |
| What is the time-zero offset? | *not stated* | — | unknown | **still blocked** |
| What propagation velocity applies? | *not mentioned* | converter default 0.1 m/ns | BLOCKED | **still blocked** |

### Evidence categories, kept separate

- **AUTHOR-STATED** — the datum is ellipsoidal WGS84; the GNSS antenna height was
  accounted for; no time-zero or air-gap correction was applied.
- **MEASURED-IN-FILE** — both elevation fields present on every trace; per-trace
  NMEA positions present; the elevation profile varies smoothly along track.
- **DERIVED-BY-SUBTERRA** — the inference that the *larger* field is the
  ellipsoidal one (see §3). An inference, not a statement by anyone.
- **USER-DECLARED** — nothing. No declaration has been made on this basis.
- **UNKNOWN** — the field mapping, the time-zero magnitude, the velocity.

## 2. What was measured in the file

Audited on `01.1/Path8.sgy` (314 traces) and across 105 activities:

| | |
|---|---|
| Format | SEG-Y, little-endian, format code 3 (int16 samples) |
| Coordinates | IEEE float32 in NMEA `ddmm.mmmm`, per trace — decodes to 52.2390 N, 6.8516 E (Enschede) |
| Elevation field A | bytes 41–44 (Receiver Group Elevation), IEEE float32, 28.372–28.412 m |
| Elevation field B | bytes 45–48 (Source Surface Elevation), IEEE float32, 72.321–72.361 m |
| Coverage | **314/314 traces carry both fields and a position** |
| Along-track profile | varies smoothly, 0.87 cm std over the line |

The file uses IEEE floats where the SEG-Y standard specifies scaled integers.
Subterra already handles this under the `ieee_nmea` coordinate encoding, and the
converter already stores **both** values — `record.elevation` from field A and
`segy_source_surface_elevation_m` from field B — while recording
`acquisition_elevation_datum: "UNDECLARED"`.

A prior stage had already found the constant offset between them and correctly
refused to name it. The author's response is exactly the evidence that refusal
was waiting for — and it is still one question short.

## 3. The field-mapping problem, and why it blocks the datum

The two candidate fields differ by **42.217–45.206 m** depending on site. That
difference is:

- **constant within a site** (all of activity 05.x: 45.177 m; all of 02.x: 45.205 m)
- **varying smoothly between sites**

That is how a **geoid separation** behaves, and not how a fixed software constant
would. For the Netherlands the NAP↔WGS84 separation is ~43–46 m, which matches.

So the evidence points to **field B (the larger) being the ellipsoidal height**
and field A being an NAP-like orthometric height. **This is an inference from
magnitude, not a statement by anyone**, and it is recorded as one.

It matters because the consequence of being wrong is a **~44 m error in every
elevation the platform reports**. `record.elevation` currently holds field A —
the value this inference says is *not* the ellipsoidal one. So applying the
author's datum to the field Subterra already stores would be wrong if the
inference is right, and right only by accident if it is wrong.

**Hence: the datum was known and not yet attachable.** One narrow question closed
it — see §5.

## 4. What the response does not establish

The author is explicit that the air-path/time-zero issue *exists* and gives no
magnitude. Accordingly nothing here records:

a numerical time-zero offset · a numerical antenna-to-ground distance · a
numerical air-gap thickness · a propagation velocity · a depth conversion · a
corrected time zero · a ground-surface depth · a vertical offset in metres or
nanoseconds.

**One misreading is worth naming explicitly.** "The antenna-height offset was
already accounted for" refers to the **GNSS rover's** antenna, and concerns the
elevation values it produced. It is *not* a GPR time-zero correction — a
different instrument and a different quantity — and it must not be read as
evidence that the GPR depth axis begins at the ground. The author's own next
sentence says the opposite.

## 5. What to ask next

**Two questions remain**, recorded in `evidence/fourtu_author.py`
(`OPEN_QUESTIONS[1]` and `[2]`). The header-field question that used to sit
here has been **answered by measurement, not by an author reply** — it does
not need asking and is not repeated below.

1. **What is the time-zero offset or air gap**, in ns or m?
   *Blocks: relating the depth axis to the ground.* The author has already
   established that this offset exists and is uncorrected; only its
   magnitude is missing.
2. **Was a propagation velocity determined for any site, and by what method?**
   *Blocks: converting time to physical depth.*

A letter asking exactly these two questions is at
[`4tu-author-letter-draft.md`](4tu-author-letter-draft.md) — **sent by email
on 2026-08-15 (operator-stated). Awaiting reply.** Sending it was the human
operator's decision, not something this platform or its tooling did on its
own, and Subterra has not independently verified delivery.

No GPR instrument manufacturer is named anywhere in held 4TU evidence — only
"air-launched 500 MHz GPR"
([`4tu-characterisation.md`](4tu-characterisation.md)). RadarMap is the
processing software the author mentioned, and the Spectre SP80 is the GNSS
rover; neither is the GPR vendor. No vendor letter is drafted on that basis —
inventing a manufacturer to have someone to write to would be exactly the
kind of unearned specificity this evidence trail exists to refuse.

## 6. Effect on readiness

Four dimensions move, four do not.

**Moved:**
- vertical datum of the GNSS elevation — UNDECLARED → author-stated, and since
  declared against SEG-Y bytes 45-48 (`docs/4tu-vertical-datum.md`)
- surface elevation profile — absent → representable, present on every trace
- GNSS antenna height — unknown → resolved
- depth-axis origin — BLOCKED (Subterra's cautious assumption) → BLOCKED (author-confirmed fact)

**Unmoved:** propagation velocity, vertical registration, absolute elevation of a
subsurface reflector, horizontal reference (which needed nothing).

The depth-origin row is the one worth dwelling on: the *state* is identical and
the *basis* is much stronger. Subterra previously refused to treat time zero as
the ground because it had no evidence either way. It now refuses because the
dataset's author says it is not. That is a better-founded BLOCKED, and it also
means the derived-depth axis the viewer shows is more wrong than assumed — it
contains an uncorrected air path on top of an uncalibrated velocity.

## 7. No state was changed in the platform

No declaration was recorded against any dataset, no readiness state was flipped
and no converter behaviour changed. The evidence is recorded; acting on it needs
the field-mapping answer.

Had a declaration been made, the architecture supports it correctly:
`SpatialDeclaration.supplied_by` names the **authority** and is explicitly
distinct from `declared_by_user_id`, the signed-in account — so "Dr. ter Huurne,
direct correspondence" is representable without pretending Subterra measured it.
