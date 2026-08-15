'use client'

import { useState } from 'react'
import { useSWRConfig } from 'swr'
import { ApiError, api } from '@/services/api'
import { buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { DeclarationKind } from '@/types/subterra'

/**
 * Asserting a spatial relationship.
 *
 * THE FORM IS SHAPED TO STOP A MEASUREMENT FROM BEING IMPLIED. Every kind
 * requires an attribution — who says so — before it will submit, because a
 * spatial claim with no author is indistinguishable from a guess, and this
 * screen is the one place a guess could enter the platform. The field is
 * labelled "who established this" rather than "source", so it reads as a
 * question about authority rather than a metadata slot to be filled with
 * anything.
 *
 * NO FIELD HAS A PREFILLED SCIENTIFIC VALUE. No default velocity, no default
 * antenna height, no suggested EPSG code. A default here would be a fabricated
 * measurement wearing a placeholder's clothes: the user would accept it, the
 * platform would record it as a declaration, and it would be indistinguishable
 * from one somebody actually knew. Placeholders show FORMAT ("0.10"), never a
 * value the form is willing to submit.
 *
 * WHAT EACH DECLARATION MEANS IS STATED ON THE FORM, in the platform's terms —
 * particularly that a velocity produces derived depth rather than measured
 * depth, and that a tie registers additively without touching the acquisition's
 * own coordinates.
 */
const FIELDS: Record<
  DeclarationKind,
  {
    title: string
    explain: string
    consequence: string
    inputs: {
      name: string
      label: string
      placeholder?: string
      hint?: string
      /** Renders a choice instead of free text, where the platform owns the vocabulary. */
      options?: { value: string; label: string }[]
      /** The unselected option's own text, when `options` is set. */
      selectPlaceholder?: string
      /** Omitted from the payload when left blank, rather than submitted empty. */
      optional?: boolean
    }[]
  }
> = {
  crs: {
    title: 'Declare the coordinate reference system',
    explain:
      'The horizontal reference the acquisition’s coordinates are expressed in.',
    consequence:
      'Recorded as supplied by a caller — never as declared by the source, which only the file itself can claim. Subterra does not verify a CRS against the coordinate values: a plausible-looking easting is not evidence of a projection.',
    inputs: [
      { name: 'code', label: 'EPSG code', placeholder: 'EPSG:32635' },
      {
        name: 'kind',
        label: 'Kind',
        placeholder: 'projected',
        hint: 'projected or geographic',
      },
    ],
  },
  vertical_datum: {
    title: 'Declare the vertical datum',
    explain:
      'What a vertical coordinate of this survey is measured from — and which one. A frame can carry two: the vertical axis, and the acquisition elevation stored with each position. They need not share a datum.',
    consequence:
      'Without this, no vertical coordinate here can be compared with one from any other source, and no absolute elevation can be computed. A datum for the acquisition elevation does NOT say what the depth axis is measured from, does not place depth zero at the ground, and does not supply a propagation velocity — so it does not, on its own, produce a physical depth or an absolute elevation for anything in the subsurface.',
    inputs: [
      { name: 'code', label: 'Datum', placeholder: 'NAP' },
      {
        name: 'applies_to',
        label: 'Which quantity',
        options: [
          { value: 'vertical_axis', label: 'The frame’s vertical axis' },
          { value: 'acquisition_elevation', label: 'The acquisition elevation stored with each position' },
        ],
        selectPlaceholder: 'choose which quantity this datum describes',
        hint:
          'The axis is what depth or elevation samples are on — for a GPR that is travel time from instrument time zero, which no geodetic datum describes. The acquisition elevation is the instrument’s own height, usually from GNSS.',
      },
      {
        name: 'field',
        label: 'Which stored field',
        optional: true,
        placeholder: 'SEG-Y bytes 45-48 (Source Surface Elevation)',
        hint:
          'Optional, and only for an acquisition elevation. Name it in the source’s own words where a source stores more than one — they need not share a datum.',
      },
    ],
  },
  antenna_offset: {
    title: 'Declare where the depth axis begins',
    explain:
      'How far the depth/time axis’ zero sat from the ground surface during acquisition. A GPR’s depth zero is instrument time zero, which is not the ground.',
    consequence:
      'This establishes the relationship between the acquisition origin and the ground reference. It does NOT establish a propagation velocity, a physical depth, a vertical datum, a surface elevation, or any validation of the number — nothing here checks that the value is true. There is no default: an offset of zero is a physical claim that the origin was on the ground.',
    inputs: [
      {
        name: 'offset_m',
        label: 'Offset (metres)',
        placeholder: '0.45',
        hint: 'positive means the reference point was ABOVE the ground; 45 cm is 0.45, not 45',
      },
      {
        name: 'measured_from',
        label: 'Measured from',
        placeholder: 'depth_axis_origin',
        hint: 'depth_axis_origin · sensor_phase_centre · sensor_housing — only depth_axis_origin answers what vertical registration asks',
      },
      {
        name: 'evidence',
        label: 'Evidence',
        placeholder: 'field_measurement',
        hint: 'field_measurement · acquisition_documentation · user_declaration · derived',
      },
    ],
  },
  depth_conversion: {
    title: 'Declare a propagation velocity',
    explain: 'Turns the measured time axis into a depth axis.',
    consequence:
      'The resulting depth is DERIVED, not measured: it is an assumption about this ground, recorded as one, and it will be labelled that way everywhere it appears. The value is checked against physically plausible bounds.',
    inputs: [
      {
        name: 'velocity_m_per_ns',
        label: 'Velocity (m/ns)',
        placeholder: '0.10',
        hint: 'between 0.01 and 0.30 m/ns — note m/ns, not cm/ns',
      },
    ],
  },
  geo_tie: {
    title: 'Define a spatial tie',
    explain:
      'Control points relating along-track distance to real coordinates, for an acquisition that carries no geographic position.',
    consequence:
      'Registration, not estimation: the acquisition’s own along-track coordinate is kept, and the tied position is written alongside it, so a tie can be corrected or discarded without destroying the measurement. Two points are usable but can never be verified; three or more are checked against a straight line.',
    inputs: [
      {
        name: 'control_points',
        label: 'Control points',
        placeholder: '0, 52.0, 4.3\n8.5, 52.0005, 4.3005',
        hint: 'one per line: along-track metres, latitude, longitude',
      },
    ],
  },
  surface_reference: {
    title: 'Link a surface model',
    explain: 'Another dataset asserted to be this survey’s surface elevation model.',
    consequence:
      'Linking is not validating. Whether the linked model can actually anchor anything is decided by its own frames — it needs an elevation axis and a declared vertical datum, and a DEM without them will be reported as unvalidated however confidently it was linked.',
    inputs: [
      { name: 'surface_dataset_id', label: 'Surface dataset ID', placeholder: 'a dataset id' },
    ],
  },
  orientation: {
    title: 'Declare the antenna heading',
    explain:
      'Which direction the antenna faced — not which direction the acquisition travelled. A line of positions implies a bearing; bearing is not orientation.',
    consequence:
      'Recorded as a claim, not a measurement: nothing here checks the number against anything. This does not come from an IMU and is not inferred from the track — declaring it here only records what somebody says the heading was.',
    inputs: [
      {
        name: 'heading_deg',
        label: 'Heading (degrees)',
        placeholder: '47.0',
        hint: '0 up to but not including 360',
      },
      {
        name: 'reference',
        label: 'Measured from',
        options: [
          { value: 'true_north', label: 'True north' },
          { value: 'magnetic_north', label: 'Magnetic north' },
          { value: 'grid_north', label: 'Grid north' },
        ],
        selectPlaceholder: 'choose what the heading is measured from',
        hint: 'True, magnetic and grid north disagree by degrees to tens of degrees — there is no default.',
      },
    ],
  },
}

function parseControlPoints(raw: string): unknown {
  return raw
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [along, lat, lon] = line.split(',').map((part) => Number(part.trim()))
      return { along_track_m: along, lat, lon }
    })
}

export function DeclarationForm({
  datasetId,
  kind,
  onDone,
  onCancel,
}: {
  datasetId: string
  kind: DeclarationKind
  onDone?: () => void
  onCancel?: () => void
}) {
  const { mutate } = useSWRConfig()
  const spec = FIELDS[kind]
  const [values, setValues] = useState<Record<string, string>>({})
  const [suppliedBy, setSuppliedBy] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const payload: Record<string, unknown> = {}
      for (const input of spec.inputs) {
        const raw = values[input.name] ?? ''
        // An omitted optional field is ABSENT, not empty. Submitting "" would
        // record that somebody named the field and named it nothing.
        if (input.optional && raw.trim() === '') continue
        payload[input.name] =
          input.name === 'control_points' ? parseControlPoints(raw) : raw
      }
      await api.declareSpatialReference(datasetId, kind, payload, suppliedBy)
      // The reference, the report and the workspace all read the frames.
      await mutate(['spatial-reference', datasetId])
      await mutate(['dataset-report', datasetId])
      await mutate(['dataset-info', datasetId])
      onDone?.()
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.detail
          : 'could not reach the Subterra API. Is the backend running?',
      )
    } finally {
      setBusy(false)
    }
  }

  const complete =
    suppliedBy.trim() !== '' &&
    spec.inputs.every((i) => i.optional || (values[i.name] ?? '').trim())

  return (
    <form onSubmit={submit} data-declaration-form={kind} className="mt-3 space-y-3">
      <div>
        <h4 className="text-sm font-medium text-foreground">{spec.title}</h4>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{spec.explain}</p>
        <p
          data-consequence
          className="mt-1.5 text-xs leading-relaxed text-muted-foreground"
        >
          {spec.consequence}
        </p>
      </div>

      {spec.inputs.map((input) => (
        <div key={input.name}>
          <label
            htmlFor={`${kind}-${input.name}`}
            className="block font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground"
          >
            {input.label}
          </label>
          {input.options ? (
            /*
              NOT PRESELECTED. The two quantities are genuinely different, and
              a preselected one would be answered by the form rather than by
              the person declaring — which is exactly how a GNSS elevation's
              datum ends up asserted about a travel-time axis.
            */
            <select
              id={`${kind}-${input.name}`}
              value={values[input.name] ?? ''}
              onChange={(e) => setValues({ ...values, [input.name]: e.target.value })}
              className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <option value="">{input.selectPlaceholder ?? 'choose one'}</option>
              {input.options.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          ) : input.name === 'control_points' ? (
            <textarea
              id={`${kind}-${input.name}`}
              rows={3}
              placeholder={input.placeholder}
              value={values[input.name] ?? ''}
              onChange={(e) => setValues({ ...values, [input.name]: e.target.value })}
              className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 font-mono text-xs text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
            />
          ) : (
            <input
              id={`${kind}-${input.name}`}
              placeholder={input.placeholder}
              value={values[input.name] ?? ''}
              onChange={(e) => setValues({ ...values, [input.name]: e.target.value })}
              className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
            />
          )}
          {input.hint && (
            <p className="mt-1 text-[11px] text-muted-foreground">{input.hint}</p>
          )}
        </div>
      ))}

      {/*
        Required. A spatial claim with no author is indistinguishable from a
        guess, and this screen is the one place a guess could enter.
      */}
      <div>
        <label
          htmlFor={`${kind}-supplied-by`}
          className="block font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground"
        >
          Who established this
        </label>
        <input
          id={`${kind}-supplied-by`}
          placeholder="site survey 2019-03-20 / PDOK documentation"
          value={suppliedBy}
          onChange={(e) => setSuppliedBy(e.target.value)}
          className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
        />
        <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
          The authority for the claim, not your account — you may be relaying somebody
          else&rsquo;s measurement. Recorded with the declaration and shown wherever it
          affects an interpretation.
        </p>
      </div>

      {error && (
        <p
          data-declaration-error
          role="alert"
          className="rounded-lg border border-destructive/40 px-3 py-2 text-xs leading-relaxed text-foreground"
        >
          {error}
        </p>
      )}

      <div className="flex gap-2">
        <button
          type="submit"
          data-action="submit-declaration"
          disabled={busy || !complete}
          className={cn(
            buttonVariants({ variant: 'default', size: 'sm' }),
            'disabled:opacity-40',
          )}
        >
          {busy ? 'Recording…' : 'Record declaration'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className={cn(buttonVariants({ variant: 'ghost', size: 'sm' }))}
        >
          Cancel
        </button>
      </div>
    </form>
  )
}
