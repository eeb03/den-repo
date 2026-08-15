# Depth-axis origin → ground

Stage 12. Where a subsurface measurement's zero sits relative to the ground —
the last of the three things an absolute elevation needs, and the one nothing
could previously express.

## What was actually missing

Stage 8's `fusion.vertical_reference.assess` has always enumerated three
requirements. Stage 11 supplied the second. The third read:

> a known offset from the depth axis ORIGIN to the ground

and was decided like this:

```python
origin = (sub_axis.origin or "").lower()
origin_is_ground = "ground surface" in origin or "maaiveld" in origin
```

**A string match standing in for a physical relationship.** Stage 8 also shipped
an `antenna_offset` declaration — and applying one recorded an `Assumption` and
nothing else, with a comment saying so. Nothing read it. So a user could declare
the offset, see it in the audit log, and watch the assessment not move.

## What a declaration now means

`VerticalAxis.origin_offset: DepthOriginOffset` — on the **axis**, which lives on
the **frame**, because a survey line is exactly the unit over which a sensor
geometry is constant. Two lines of one survey may legitimately differ, and a
dataset-wide value could not express that.

```
offset_m        metres, always — the unit is in the field name
measured_from   depth_axis_origin | sensor_phase_centre | sensor_housing
measured_to     the ground reference (default "ground surface")
evidence        field_measurement | acquisition_documentation
                | user_declaration | derived
supplied_by     the AUTHORITY, not the account that typed it
verified        always false — see below
```

### Three reference points, not one string

These were previously one free-text field. They are not interchangeable:

| | |
|---|---|
| `depth_axis_origin` | where sample zero sits — for a GPR, instrument time zero, set by the electronics. **The only one vertical registration is about.** |
| `sensor_phase_centre` | where the pulse effectively leaves the antenna |
| `sensor_housing` | what a tape measure touches |

A phase-centre height is a real measurement that **does not answer the
question** until somebody also relates it to time zero. Declaring one is
accepted, recorded, and reported as insufficient with the reason — it does not
silently satisfy the requirement.

## Sign convention

```
positive  =  the reference point is ABOVE the ground
```

**Not chosen here.** Stage 8's declaration has recorded `positive_direction:
"sensor above ground"` since it was introduced; inverting it now would silently
flip every value already declared under it. So a cart-mounted antenna 0.45 m off
the ground is `+0.45`, and a sensor lowered into a trench is negative.

For a depth axis (`positive_down`), the ground therefore lies at `+offset_m` on
that axis: a sample at depth *d* is *(d − offset_m)* below ground. **Nothing
performs that arithmetic yet** — it is written down in
`schemas/spatial.py::OFFSET_POSITIVE_MEANS` so that whatever eventually does
cannot get the sign backwards. Zero, positive, negative and non-finite values
are each tested.

## Evidence, and what "verified" means

`evidence` says where the number came from. `verified` is separate and is
**always false**: Subterra has no way to check an offset against anything, and
documentation can be authoritative and still unchecked against this particular
acquisition. Marking a declaration verified would make it look like a
measurement.

Both are required — neither is defaulted. The reference point used to fall back
to "sensor phase centre", which quietly answered a question the caller had not
been asked.

## Syntax is not physics

Validation rejects non-numbers, NaN, infinity, and magnitudes beyond ±10 m. That
bound is **representability, not a law**: beyond a few metres this is no longer a
sensor-to-ground geometry the platform models, and a mistyped centimetre value
lands there rather than in a dataset — the error says *"the unit is metres — 45
cm is 0.45, not 45."*

Nothing checks that an accepted value is **true**, and the assessment says so
wherever the offset appears.

## The dependency graph

Declaring the offset removes exactly one requirement. It does not make anything
ready on its own:

| | |
|---|---|
| datums undeclared | still `registration_required` — the offset changes nothing about that |
| time axis, no velocity | still blocked: *"no velocity was supplied"*. Knowing where the axis begins does not turn nanoseconds into metres |
| phase-centre offset only | still blocked, with the reason |
| datums declared and equal **+** a depth axis **+** an axis-origin offset | `absolute_elevation` |

The `vertical_reference` dimension's **action follows the graph**: with the datum
declared and the origin unplaced, it asks for the offset rather than the datum
the caller has already given.

## What it does not touch

`origin` is unchanged, every sample is unchanged, every stored depth is
unchanged. This records a **relationship**, not a shift. Rewriting `origin`
would make the frame claim its zero had moved and every stored sample would
silently mean something else; shifting samples needs a velocity this stage
deliberately does not supply. A test parses the apply path and asserts it never
calls `save_records`.

Stage 8's staleness rule applies unchanged: a new declaration makes products
computed before it stale, and nothing is recomputed.

## API and database

**No new endpoint and no migration.** The existing
`POST /api/spatial/{id}/declarations` with `kind: antenna_offset` expresses this
completely; the value lands on the frame, which is where every consumer already
reads spatial reference from. `SpatialDeclaration` already stores the claim, its
author and its supersession.

## The real data

Against the held Lazaresti GPR depth slice and the COP30 surface from Stage 11:
the workflow accepts the declaration, records it with its authority, and the
assessment moves exactly as far as the evidence allows and no further.

**No offset for the held GPR data is asserted as true anywhere in this
repository.** Nobody has supplied one for that survey, and the value used in
verification is a clearly labelled test declaration, not a claim about
Lazaresti.

## Limitations

- **Nothing verifies an offset.** It records who said it, unverified.
- **No arithmetic uses it yet.** The relationship is expressed and the sign
  convention pinned; converting a sample's depth to an elevation belongs to the
  stage that has a defensible velocity.
- **A phase-centre or housing offset is recorded but insufficient**, and there is
  no workflow yet for relating one to the axis origin.
