'use client'

import { useState } from 'react'
import Link from 'next/link'
import { ApiError, api } from '@/services/api'
import { buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { formatCount } from '@/lib/format'
import type { ImportJob } from '@/types/subterra'

/**
 * What arrived, before anything is ingested.
 *
 * WHY THERE IS A STOP HERE AT ALL. Before FileDrop, an upload was queued the
 * moment it landed, and the first thing a user learned about a file Subterra
 * could not place was a finished dataset that could not be placed. Ingestion is
 * not free — it is the slowest thing the platform does — so the decision to
 * spend it belongs to somebody who has been told what the file is and what it
 * will not support.
 *
 * IT SHOWS WHAT THE FORMAT CAN CARRY, NOT WHAT THIS FILE DECLARES. Nothing has
 * been parsed at this point: identification reads the registry, the extension
 * and the size. So the spatial section is phrased as an expectation, and the
 * dataset report answers the real question once the file has been read. Saying
 * "CRS: EPSG:4326" here would be a guess wearing a fact's clothes.
 *
 * INGESTION READINESS IS NOT SPATIAL READINESS. A file with no usable spatial
 * reference is still worth parsing, processing and assessing, so this screen
 * offers to proceed even when the spatial expectation is poor — and says which
 * later stage will be blocked instead of pretending the file is unusable.
 */
export function AcquisitionReview({
  job,
  onAccepted,
}: {
  job: ImportJob
  onAccepted?: (job: ImportJob) => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // A raster band carries numbers and no statement of what they measure.
  // Undeclared by default: the platform must not assume the answer.
  const [bandIsElevation, setBandIsElevation] = useState(false)
  // '' means "not specified" -- the file's bytes are read as the SEG-Y
  // standard (int32_scaled) either way, so an empty selection and an
  // explicit 'int32_scaled' selection are the same real outcome. Only a
  // conscious switch to the vendor deviation is ever sent.
  const [coordinateEncoding, setCoordinateEncoding] = useState('')
  const identification = job.identification

  async function accept() {
    setBusy(true)
    setError(null)
    try {
      const options: { band_is_elevation?: boolean; coordinate_encoding?: string } = {}
      if (canDeclareElevation) options.band_is_elevation = bandIsElevation
      if (canChooseCoordinateEncoding && coordinateEncoding) {
        options.coordinate_encoding = coordinateEncoding
      }
      const { job: queued } = await api.acceptAcquisition(job.id, options)
      onAccepted?.(queued)
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

  if (!identification) return null

  const rejected = !identification.parser_available
  // Only formats whose converter can act on it. Offering the choice elsewhere
  // would invite a declaration that changes nothing.
  const canDeclareElevation = identification.detected_format === 'geotiff'
  const canChooseCoordinateEncoding = identification.detected_format === 'segy'
  const duplicates = identification.duplicates

  return (
    <div data-acquisition-review={job.state} className="space-y-4">
      <div>
        <h3 className="text-sm font-medium text-foreground">
          {identification.original_filename ?? 'the uploaded file'}
        </h3>
        <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <div>
            Format:{' '}
            <span className="text-foreground">{identification.detected_format}</span>
          </div>
          <div>
            Size:{' '}
            <span className="text-foreground">
              {formatCount(identification.size_bytes)} bytes
            </span>
          </div>
          <div>
            Declared as:{' '}
            <span className="text-foreground">
              {identification.declared_modality ?? 'not declared'}
            </span>
          </div>
          <div className="truncate">
            Checksum:{' '}
            <code data-checksum className="font-mono text-[11px] text-foreground">
              {identification.checksum?.slice(0, 16)}…
            </code>
          </div>
        </dl>
      </div>

      {/* Rejected: say what it was, and what would work instead. */}
      {rejected && (
        <div data-rejected className="text-xs leading-relaxed text-muted-foreground">
          <p className="text-foreground">Subterra cannot read this file.</p>
          <p className="mt-1">{identification.rejection_reason}</p>
          {identification.supported_formats && (
            <p className="mt-1">
              Readable formats: {identification.supported_formats.join(', ')}
            </p>
          )}
        </div>
      )}

      {/*
        The modality came from the uploader, not from the file. Stated because
        a wrong declaration produces a dataset that parses cleanly and means
        something else.
      */}
      {identification.ambiguous_format && (
        <p data-ambiguous className="text-xs leading-relaxed text-muted-foreground">
          {identification.ambiguity_note}
        </p>
      )}

      {duplicates?.is_duplicate && (
        <div data-duplicate className="text-xs leading-relaxed text-muted-foreground">
          <p className="text-foreground">
            These exact bytes are already held.
          </p>
          <p className="mt-1">{duplicates.note}</p>
          {(duplicates.datasets ?? []).map((d) => (
            <p key={d.dataset_id} className="mt-1">
              Dataset:{' '}
              <Link
                href={`/datasets/${encodeURIComponent(d.dataset_id)}/report`}
                className="text-primary underline-offset-4 hover:underline"
              >
                {d.name}
              </Link>
            </p>
          ))}
        </div>
      )}

      {!rejected && (
        <div data-spatial-expectation className="text-xs leading-relaxed text-muted-foreground">
          <p className="font-mono text-[10px] uppercase tracking-[0.14em]">
            What this format can carry
          </p>
          <p className="mt-1">Horizontal: {identification.spatial_expectation.horizontal}</p>
          <p className="mt-0.5">Vertical: {identification.spatial_expectation.vertical}</p>
          {identification.spatial_expectation.missing.length > 0 && (
            <>
              <p className="mt-1.5">Likely to need establishing afterwards:</p>
              <ul className="mt-1 space-y-0.5">
                {identification.spatial_expectation.missing.map((item) => (
                  <li key={item} data-expected-missing className="flex gap-2">
                    <span aria-hidden className="select-none text-primary">
                      &middot;
                    </span>
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
          <p className="mt-1.5">{identification.spatial_expectation_note}</p>
          {/*
            The consequence, stated plainly. Incomplete spatial reference does
            not block ingestion -- it blocks reconstruction, which is a
            different and later thing.
          */}
          <p className="mt-1.5">
            Missing spatial information does not stop this file being read, processed
            and assessed. It stops 3D reconstruction, which the dataset report and the
            spatial workflow will explain once it is in.
          </p>
        </div>
      )}

      {/*
        THE SURFACE ANCHOR STARTS HERE. A raster band is elevation, reflectance
        or temperature indistinguishably, and until somebody says which, the
        file cannot anchor a depth to the ground. Undeclared is the default and
        a legitimate answer; declaring it is recorded as the caller's claim, not
        as something the file stated.
      */}
      {!rejected && canDeclareElevation && (
        <div data-band-declaration className="text-xs leading-relaxed text-muted-foreground">
          <label className="flex items-start gap-2">
            <input
              id="band-is-elevation"
              type="checkbox"
              className="mt-0.5"
              checked={bandIsElevation}
              onChange={(e) => setBandIsElevation(e.target.checked)}
            />
            <span>
              Band 1 of this raster is <strong className="text-foreground">elevation in
              metres</strong>.
            </span>
          </label>
          <p className="mt-1.5">
            The file does not say what its band measures. Declaring this makes the
            raster usable as a surface model — the thing a subsurface depth is
            eventually measured down from — and is recorded as your claim, not as
            something the file stated. Leave it unticked if you do not know: an
            undeclared band is a correct answer.
          </p>
          <p className="mt-1.5">
            A surface still needs a declared vertical datum before it can anchor
            anything. The spatial workflow asks for that after import.
          </p>
        </div>
      )}

      {/*
        COORDINATE ENCODING. SEG-Y's own standard says these header fields
        are scaled integers, and that stays the safe default -- most SEG-Y
        files follow it, and this file's bytes cannot say otherwise either
        way. A minority of GPR vendors instead write IEEE floats holding
        NMEA coordinates, which the bytes cannot reveal on their own, so it
        is a conscious declaration, never a guess.
      */}
      {!rejected && canChooseCoordinateEncoding && (
        <div data-coordinate-encoding-declaration className="text-xs leading-relaxed text-muted-foreground">
          <label className="flex flex-col gap-1">
            <span>Coordinate encoding</span>
            <select
              id="coordinate-encoding"
              value={coordinateEncoding}
              onChange={(e) => setCoordinateEncoding(e.target.value)}
              className="rounded-md border border-border bg-background px-2 py-1 text-xs text-foreground"
            >
              <option value="">SEG-Y standard (default) — scaled integer coordinates</option>
              <option value="ieee_nmea">
                Vendor deviation — IEEE float coordinates holding NMEA geographic positions
              </option>
            </select>
          </label>
          <p className="mt-1.5">
            Choose how coordinates already stored in this file&apos;s trace headers should be
            decoded. This does not add missing coordinates, and does not validate their
            accuracy — it only controls how the existing header bytes are interpreted. Leave
            this on the default unless you know your instrument uses the vendor deviation.
          </p>
        </div>
      )}

      {error && (
        <p
          data-acquisition-error
          role="alert"
          className="rounded-lg border border-destructive/40 px-3 py-2 text-xs leading-relaxed text-foreground"
        >
          {error}
        </p>
      )}

      {!rejected && (
        <button
          type="button"
          data-action="accept-acquisition"
          disabled={busy}
          onClick={accept}
          className={cn(buttonVariants({ variant: 'default', size: 'sm' }))}
        >
          {busy ? 'Starting…' : 'Import this file'}
        </button>
      )}
    </div>
  )
}
