# Subterra AI — Master Roadmap

**The destination is the product described below — not merely a better research
dashboard.** The research-grade provenance, validation, and conservative
scientific gates are the foundation that makes the product trustworthy.

### North-star product

> **Connect a subsurface sensing device—or upload an existing dataset—and
> Subterra transforms the raw measurements into an evidence-backed, spatially
> registered 3D representation of the underground environment, with uncertainty
> clearly shown to the user.**

The eventual experience should be:

**Scan → Process → Understand → Reconstruct → Explore**

---

# PHASE 0 — Lock the foundation

**Status: essentially complete**

### Existing

- GPR format ingestion
- CSV/TSV/XYZ
- SEG-Y/SGY
- LAS/LAZ
- TIFF/DEM
- IDS formats
- Radargram visualization
- Validation
- preprocessing
- provenance
- coordinate/reference handling
- fusion
- candidate generation
- benchmark infrastructure
- scientific integrity guards
- dataset workspace
- asynchronous import
- ownership
- authentication
- password reset
- rate limiting
- landing experience

### Goal

Don't add more AI yet. Make sure the system has a **trusted data contract**:

```
RAW DATA
   ↓
FORMAT IDENTIFICATION
   ↓
NORMALIZATION
   ↓
VALIDATION
   ↓
PROVENANCE
   ↓
REFERENCE FRAME
   ↓
PROCESSED DATA
```

Every later AI result depends on this.

---

# PHASE 1 — Turn Subterra into a real SaaS product

**Goal: a stranger can create an account and use Subterra without touching your
terminal.**

### 1. Account

```
Landing
   ↓
Create account
   ↓
Login
   ↓
Workspace
```

### 2. Dataset management

Users need:

- My datasets
- Upload dataset
- Dataset status
- Dataset metadata
- Delete dataset
- Rename dataset
- Dataset processing history
- Dataset provenance

### 3. Import experience

The user should see:

```
Upload
   ↓
Detect format
   ↓
Validate
   ↓
Process
   ↓
Ready
```

Instead of:

> "Upload succeeded."

show:

> **Dataset ready**
>
> 157,040 traces processed
> Coordinate system: declared
> Vertical datum: not declared
> Survey frame: available
> Quality: good
> 12 candidate regions identified

That is the beginning of the product experience.

---

# PHASE 2 — Build the hardware abstraction layer

Do **not** immediately try to support every GPR manufacturer. Build the
abstraction first.

```
                    SUBTERRA
                       │
                DeviceProfile
                       │
                DeviceAdapter
                       │
        ┌──────────────┼──────────────┐
        │              │              │
   FileDrop        Network         Serial
        │              │              │
        └──────────────┼──────────────┘
                       ↓
                 Acquisition
                    Session
                       ↓
                 Raw dataset
                       ↓
               Existing pipeline
```

### DeviceProfile

```
Manufacturer
Model
Sensor type
Frequency
Channels
Sampling configuration
Coordinate capability
Positioning capability
Supported export formats
```

### First adapter: FileDrop

You don't need physical hardware immediately. Many instruments already export
files.

**GPR device → exported file → Subterra watches/imports it**

This lets you prove the acquisition architecture without reverse-engineering
proprietary protocols.

### Second generation

- USB
- Serial
- Ethernet
- Wi-Fi
- vendor APIs/SDKs

Only where documentation/hardware access permits.

---

# PHASE 3 — Build the acquisition session

Now Subterra understands **a scan**, rather than merely a file.

Create `AcquisitionSession`, containing:

```
device
operator
start_time
end_time
survey_area
coordinate_system
vertical_reference
position_source
acquisition_configuration
raw_files
processing_version
```

Then:

```
DEVICE
 ↓
ACQUISITION SESSION
 ↓
RAW TRACE STREAM
 ↓
DATASET
```

This is critical for your eventual AI because the AI needs context.

---

# PHASE 4 — Spatial intelligence

Your future 3D reconstruction is only as good as your spatial information.

You need to establish:

**Horizontal position** — Where was the antenna?
**Vertical reference** — What does "depth" actually mean?
**Orientation** — Which direction was the antenna moving?
**Surface** — What does the ground surface look like?
**Coordinate reference** — What coordinate system is everything expressed in?

Eventually:

```
GPR traces
     +
GNSS
     +
IMU
     +
surface DEM
     +
survey geometry
     ↓
COMMON SPATIAL FRAME
```

This is where your existing **CRS/refusal-to-fake-localisation discipline**
becomes extremely valuable.

---

# PHASE 5 — Signal intelligence

```
Raw trace
 ↓
Time-zero correction
 ↓
Dewow
 ↓
Background removal
 ↓
Gain
 ↓
Filtering
 ↓
Normalization
 ↓
Trace alignment
 ↓
Quality assessment
```

But don't just make pretty images. Each transformation needs provenance:

```
RAW
  ↓
dewow
  ↓
background removal
  ↓
gain
  ↓
filter
```

The user should eventually be able to inspect this.

---

# PHASE 6 — Candidate detection

Do **not** jump straight to:

> "Pipe detected."

Start with:

> **Candidate region**

For example:

```
Candidate C-014

Geometry:
depth-elongated

Signal evidence:
strong

Spatial coherence:
high

Cross-line consistency:
medium

Confidence:
not a single score
```

Your existing four-part confidence model should remain.

The AI should be allowed to say:

> "Something anomalous appears here."

before it is allowed to say:

> "This is probably a pipe."

---

# PHASE 7 — Learn from multiple modalities

Initially `GPR`. Then:

```
GPR
+
LiDAR / DEM
+
GNSS
+
photogrammetry
+
electromagnetic data
+
magnetometry
+
other subsurface sensors
```

The key architecture:

```
                SUBTERRA DATA MODEL
                       │
       ┌───────────────┼───────────────┐
       ↓               ↓               ↓
      GPR            LiDAR            GNSS
       ↓               ↓               ↓
       └───────────────┼───────────────┘
                       ↓
                Spatial fusion
                       ↓
              Subsurface model
```

**Modality-agnostic doesn't mean "we support everything."** It means the core
model isn't architecturally tied to one sensor.

---

# PHASE 8 — Validated object interpretation

Only now should you seriously pursue:

```
candidate
   ↓
classification
   ↓
object hypothesis
```

Potential categories eventually:

- pipe
- cable
- void
- foundation
- buried object
- geological boundary
- unknown

But these labels must come from **validated models and evidence**.

You already have the correct rule:

> Candidate ≠ Detection.

Keep it.

Eventually:

```
Candidate
   ↓
Evidence aggregation
   ↓
Model inference
   ↓
Validation
   ↓
Object hypothesis
```

And the UI should communicate uncertainty. For example:

> **Possible utility-like linear structure**
>
> Evidence: radar geometry + spatial continuity
> Classification confidence: moderate
> Absolute localisation: unavailable

That's much more trustworthy than:

> **PIPE — 94%**

---

# PHASE 9 — 3D subsurface reconstruction

```
Surface
────────────────────────
       ↓
       ↓
     object
    ╱──────╲
   ╱        ╲
────────────────────────
       ↓
   subsurface
```

### Level 1 — 3D visualization

Convert measured points/candidates into 3D geometry. Achievable relatively early.

### Level 2 — 3D reconstruction

Combine radar responses, survey trajectory, depth/time conversion, multiple
profiles, and surface geometry to create a volumetric representation.

### Level 3 — photorealistic underground reconstruction

The ambitious end goal — something that feels like:

> **"a photograph of what is underground."**

But this should be understood as an **inference**, not literal photography. The
visualization should therefore include uncertainty/transparency:

```
HIGH EVIDENCE
████████

MEDIUM EVIDENCE
██████

LOW EVIDENCE
██
```

That distinction could become one of Subterra's strongest differentiators.

---

# PHASE 10 — Interactive underground world

```
                 SURFACE
─────────────────────────────────

        Building
           │
           │
      ┌────┴─────┐
      │          │
      │   PIPE   │
      │     ╲    │
      │      ╲   │
──────┴───────╲──┴───────────────

          CABLE
             ╲──────────

               VOID
              ╭────╮
              ╰────╯
```

The user can rotate, zoom, slice vertically, hide/show layers, inspect
candidates, inspect raw radargrams, compare scans, view surface terrain, click
an underground object, and see the evidence supporting it.

And crucially: **clicking a 3D object should take you back to the underlying
radar evidence.**

```
3D object
    ↓
interpretation
    ↓
candidate
    ↓
radar response
    ↓
raw trace
    ↓
original measurement
```

---

# PHASE 11 — Hardware + real-time scanning

```
Connect device
       ↓
Device recognized
       ↓
Calibration
       ↓
Start survey
       ↓
Live radargram
       ↓
Live positioning
       ↓
Live candidate generation
       ↓
3D model builds progressively
```

Eventually:

> **You walk across the site while Subterra builds the underground model behind
> you.**

---

# PHASE 12 — Expert → non-expert translation

### Expert mode

radargrams · amplitudes · preprocessing · CRS · acquisition parameters ·
candidate geometry · confidence dimensions · provenance · raw data

### Standard mode

underground objects · surfaces · anomalies · evidence · uncertainty

### Non-expert mode

> **Possible buried structure**
>
> Found approximately along this path.
> Evidence: 4 radar profiles.
> Interpretation confidence: Moderate.
> Exact position: Not available because the survey reference frame is incomplete.

That is how you make complex geophysics accessible **without pretending the AI
knows more than it does.**

---

# PHASE 13 — Validation laboratory

```
Known site
 ↓
Known objects
 ↓
Known coordinates
 ↓
Known materials
 ↓
Subterra prediction
 ↓
Compare
 ↓
Measure error
```

Benchmark matrix:

| Dataset | Candidate recall | Localisation error | Classification | 3D reconstruction |
|---|---|---|---|---|
| TU1208 | measured | measured | measured | measured |
| Dataset B | measured | measured | measured | measured |
| Dataset C | measured | measured | measured | measured |

This is how you move from **"cool demo"** to **"validated technology."**

---

# PHASE 14 — The Subterra Intelligence Engine

```
             SUBTERRA INTELLIGENCE ENGINE
                         │
       ┌─────────────────┼─────────────────┐
       ↓                 ↓                 ↓
    SIGNAL            SPATIAL          CONTEXT
   EVIDENCE           EVIDENCE          DATA
       │                 │                 │
       └─────────────────┼─────────────────┘
                         ↓
                  EVIDENCE FUSION
                         ↓
                 CANDIDATE MODEL
                         ↓
              INTERPRETATION MODEL
                         ↓
                 3D RECONSTRUCTION
                         ↓
                 UNCERTAINTY MODEL
```

This becomes the core intellectual property of Subterra.

---

# PHASE 15 — The final product

### User sees:

**Start a survey** or **Upload existing data**

Then:

```
PROCESSING
██████████████████░░ 87%

Building spatial model...
Analyzing radar responses...
Cross-referencing survey geometry...
Generating candidate structures...
```

Then:

# Your underground model

A 3D environment. Click something:

> **Candidate structure**

Click again:

> Evidence

And the system shows the radargram that produced the hypothesis.

That is the fundamental product loop.

---

# The roadmap in one picture

```
                 SUBTERRA AI
                      │
                      ▼
              ┌───────────────┐
              │ DATA PLATFORM │
              └───────┬───────┘
                      │
        ┌─────────────┴─────────────┐
        ▼                           ▼
   UPLOAD DATA                  HARDWARE
        │                           │
        └─────────────┬─────────────┘
                      ▼
                NORMALIZATION
                      │
                      ▼
                 VALIDATION
                      │
                      ▼
             SIGNAL PROCESSING
                      │
                      ▼
              SPATIAL REGISTRATION
                      │
                      ▼
                DATA FUSION
                      │
                      ▼
             CANDIDATE GENERATION
                      │
                      ▼
             AI INTERPRETATION
                      │
                      ▼
             3D RECONSTRUCTION
                      │
                      ▼
             UNCERTAINTY MODEL
                      │
                      ▼
          ┌──────────────────────┐
          │ UNDERGROUND DIGITAL  │
          │       MODEL          │
          └──────────────────────┘
                      │
             ┌────────┴────────┐
             ▼                 ▼
         EXPERT VIEW       SIMPLE VIEW
```

## Development order

**Now →**

1. SaaS/product shell ✅
2. Upload/import ✅
3. Ownership/authentication ✅
4. Password recovery ✅
5. Real email delivery ✅
6. Dataset reports
7. Better dataset management
8. Spatial reference workflow
9. FileDrop acquisition
10. Device abstraction
11. Acquisition sessions
12. Real hardware adapter
13. Candidate intelligence
14. Ground-truth benchmarks
15. Validated object detection
16. Multi-modal fusion
17. 3D reconstruction
18. Interactive underground model
19. Real-time scanning + reconstruction
20. Non-expert interpretation experience
