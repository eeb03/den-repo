# Draft letter to Dr. ter Huurne — Track 1 correspondence

**Status: SENT by email on 2026-08-15 (operator-stated). AWAITING REPLY.**
This file is a prepared email body, ready for
the human operator to review, edit and send at their own discretion.
Nothing on this platform sends correspondence automatically; producing this
draft does not constitute contacting the author.

**Recipient:** Dr. ter Huurne, author of the 4TU utility-survey GPR dataset
and its accompanying Data in Brief article, and of the earlier reply quoted
verbatim in `evidence/fourtu_author.py`.

**Purpose:** ask the two questions that remain outstanding after that reply
— `OPEN_QUESTIONS[1]` (time-zero / air-gap magnitude) and `[2]` (propagation
velocity) in `evidence/fourtu_author.py`. The one question that reply left
genuinely unresolved for us to answer ourselves — which SEG-Y field holds
the ellipsoidal height — was since resolved by measurement against the AHN
terrain model and is **not** re-asked here; see
[`4tu-author-evidence.md`](4tu-author-evidence.md) §5.

---

## Email body

> Subject: Two follow-up questions on the utility-survey GPR dataset
>
> Dear Dr. ter Huurne,
>
> Thank you again for your earlier reply about the vertical reference of the
> GNSS elevations in the utility-survey dataset — that was very helpful, and
> we were able to confirm from the SEG-Y trace headers themselves (checked
> against the AHN terrain model across the full corpus) which of the two
> elevation fields carries the ellipsoidal height, so there's no need to
> revisit that.
>
> Two further questions remain open on our side, both about relating the GPR
> depth axis itself to the ground:
>
> 1. You mentioned that no time-zero correction or air-gap removal was
>    applied to the published SEG-Y files, so the ground surface does not
>    necessarily correspond to depth zero. Do you have a value for that
>    offset — either the time-zero shift in nanoseconds, or the physical
>    antenna-to-ground air gap in metres — for the acquisitions as
>    published? Even an approximate or typical value, or a description of
>    how it could be estimated from the acquisition setup, would help.
>
> 2. Was a propagation velocity ever determined for the surveyed ground at
>    any of the sites — for example from a common-midpoint survey, hyperbola
>    fitting on a known target, or a manufacturer-supplied default for the
>    soil conditions? We currently have no site-specific velocity for this
>    dataset and would rather ask than assume one.
>
> For context: we've checked what else is openly available that might supply
> either of these independently, and found nothing that transfers to this
> specific instrument and survey — so your own records, if you have them,
> would be the most direct route.
>
> Thank you again for your time, and apologies for the second round of
> questions.
>
> Best regards,
> [sender name]

---

## Notes for whoever sends this

- **Fill in the sender name** before sending; this draft deliberately leaves
  it blank rather than inventing a signatory.
- **The "context" paragraph is the only place external audit work is
  mentioned, and it names no specifics.** It does not cite Grimsel, Wurtsmith,
  TestUM, or any candidate number — per the reviewing controller's explicit
  instruction, because none of those values transfers to this dataset and
  naming them would invite exactly the kind of borrowed-number reasoning
  this evidence trail refuses everywhere else. If you want to say more about
  what was checked, that is your call to make when sending, not something
  pre-loaded into the draft.
- **No vendor letter accompanies this.** No GPR manufacturer is named in any
  held 4TU evidence (`4tu-characterisation.md` records only "air-launched
  500 MHz GPR"), so there is no addressee to write to without guessing one.
  If Dr. ter Huurne's reply names the instrument, drafting a vendor letter
  at that point would be well-founded; doing it now would not be.
- **This draft asks exactly the two questions already recorded as
  outstanding** in `evidence/fourtu_author.py`. If the reply arrives, record
  it there the same way the first one was recorded — quoted verbatim,
  attributed, `verified_by_subterra=False` until independently checked — not
  paraphrased into a number the platform then treats as measured.
