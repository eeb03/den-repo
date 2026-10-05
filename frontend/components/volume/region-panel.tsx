'use client'

import { useState } from 'react'
import useSWR from 'swr'
import { Button } from '@/components/ui/button'
import { formatLength } from '@/lib/regions'
import { ApiError, api } from '@/services/api'
import type { RegionPreview, RegionReviewStatus, RegionSet, ResponseRegion } from '@/types/region'

const REVIEW_LABEL: Record<Exclude<RegionReviewStatus, 'unreviewed'>, string> = {
  confirmed_response: 'Confirm response',
  rejected_response: 'Reject response',
  uncertain: 'Uncertain',
}

/**
 * Response regions for one volume. A region is a coherent reconstructed
 * response above a stated, target-independent criterion -- never an object,
 * a class or a material, and nothing here offers to name one. Generation is
 * an explicit preview -> confirm; opening the viewer generates nothing.
 */
export function RegionPanel({
  datasetId, volumeId, set, onGenerated, showRegions, onShowRegions, selected, onSelect, onGoTo,
}: {
  datasetId: string
  volumeId: string
  set: RegionSet | undefined
  onGenerated: (setId: string) => void
  showRegions: boolean
  onShowRegions: (v: boolean) => void
  selected: string | null
  onSelect: (id: string | null) => void
  onGoTo: (r: ResponseRegion, where: 'centroid' | 'peak') => void
}) {
  const [preview, setPreview] = useState<RegionPreview | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const detail = useSWR(set && selected ? ['region', datasetId, volumeId, set.id, selected] : null,
    () => api.getRegion(datasetId, volumeId, set!.id, selected!), { revalidateOnFocus: false })
  const [notes, setNotes] = useState('')

  return (
    <div className="space-y-2 px-3 pb-3 text-xs" data-testid="region-panel">
      {set ? (
        <>
          <label className="flex items-center gap-2">
            <input type="checkbox" aria-label="Show response regions" checked={showRegions} onChange={(e) => onShowRegions(e.target.checked)} />
            <span>Show response regions <span className="text-muted-foreground">({set.regions.length}, unclassified)</span></span>
          </label>
          {set.staleness.stale && (
            <p className="rounded bg-amber-500/15 px-1.5 py-0.5 text-amber-500" data-testid="regions-stale">
              STALE: {set.staleness.reasons.join('; ')}
            </p>
          )}
          <p className="text-muted-foreground">
            {set.algorithm} {set.algorithm_version} · {set.migrated ? 'migrated volume' : 'NOT migrated'} · built {set.created_at.slice(0, 19).replace('T', ' ')} UTC
          </p>
          <ul className="max-h-48 space-y-1 overflow-y-auto" data-testid="region-list">
            {set.regions.map((r) => (
              <li key={r.id}>
                <button type="button" aria-pressed={selected === r.id} onClick={() => { onSelect(r.id); onGoTo(r, 'peak') }}
                  className={`flex w-full justify-between gap-2 rounded border px-1.5 py-1 text-left ${selected === r.id ? 'border-amber-400 bg-amber-400/10' : 'border-border'}`}>
                  <span>{r.id.split('-').pop()} · {formatLength(r.physical_extent.x, 'm')} × {formatLength(r.physical_extent.y, 'm')} · top {formatLength(r.bounds.z_min, r.z_unit)}</span>
                  <span className="text-muted-foreground">{r.evidence_score.toFixed(2)}{r.status === 'low_support' ? ' · low support' : ''}{r.review.status !== 'unreviewed' ? ` · ${r.review.status.replace('_response', '')}` : ''}</span>
                </button>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="text-muted-foreground">No response regions have been generated for this volume.</p>
      )}

      <div className="flex flex-wrap gap-1.5">
        <Button size="xs" variant="outline" disabled={busy !== null} onClick={async () => {
          setBusy('preview'); setError(null)
          try { setPreview(await api.previewRegions(datasetId, volumeId)) } catch (e) { setError(e instanceof ApiError ? e.detail : String(e)) }
          setBusy(null)
        }}>{busy === 'preview' ? 'Checking…' : 'Preview regions'}</Button>
        {preview?.possible && (
          <Button size="xs" disabled={busy !== null} onClick={async () => {
            setBusy('create'); setError(null)
            try { const s = await api.createRegions(datasetId, volumeId); setPreview(null); onGenerated(s.id); onShowRegions(true) } catch (e) { setError(e instanceof ApiError ? e.detail : String(e)) }
            setBusy(null)
          }}>{busy === 'create' ? 'Generating…' : 'Confirm: generate regions'}</Button>
        )}
      </div>
      {preview && (
        <div className="space-y-0.5 rounded border border-border p-2" data-testid="region-preview">
          <p className={preview.possible ? 'font-medium text-emerald-500' : 'font-medium text-destructive'}>
            {preview.possible ? `≈ ${preview.estimated_region_count} region(s)` : 'Refused'}
          </p>
          {preview.refusals.map((r) => <p key={r} className="text-destructive">• {r}</p>)}
          <p className="text-muted-foreground">{preview.algorithm}: {preview.threshold_method}</p>
          {preview.rejected && <p className="text-muted-foreground">rejected: {Object.entries(preview.rejected).map(([k, v]) => `${k.replace(/_/g, ' ')} ${v}`).join(' · ')}</p>}
          {preview.notes.map((n) => <p key={n} className="text-amber-500">{n}</p>)}
        </div>
      )}
      {error && <p role="alert" className="text-destructive">{error}</p>}

      {set && selected && detail.data && <RegionDetail r={detail.data} onGoTo={onGoTo} notes={notes} setNotes={setNotes}
        onReview={async (status) => {
          setBusy('review'); setError(null)
          try { await api.reviewRegion(datasetId, volumeId, set.id, selected, status, notes || undefined); setNotes(''); await detail.mutate() } catch (e) { setError(e instanceof ApiError ? e.detail : String(e)) }
          setBusy(null)
        }} busy={busy === 'review'} />}
    </div>
  )
}

function RegionDetail({ r, onGoTo, onReview, notes, setNotes, busy }: {
  r: ResponseRegion
  onGoTo: (r: ResponseRegion, where: 'centroid' | 'peak') => void
  onReview: (s: Exclude<RegionReviewStatus, 'unreviewed'>) => void
  notes: string
  setNotes: (v: string) => void
  busy: boolean
}) {
  const u = r.z_unit
  const pct = (v: number) => `${(100 * v).toFixed(0)}%`
  const ev = r.evidence[0]
  return (
    <div className="space-y-1.5 rounded-lg border border-amber-400/40 p-2" data-testid="region-detail">
      <p className="font-medium">Region {r.id.split('-').pop()} <span className="text-muted-foreground">— {r.status === 'low_support' ? 'LOW SUPPORT' : 'proposed'}, unclassified</span></p>
      <p className="text-muted-foreground">{r.meaning}</p>
      <div className="flex gap-1.5">
        <Button size="xs" variant="outline" onClick={() => onGoTo(r, 'centroid')}>Go to centroid</Button>
        <Button size="xs" variant="outline" onClick={() => onGoTo(r, 'peak')}>Go to peak</Button>
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5" data-testid="region-measurements">
        <dt className="text-muted-foreground">Centroid</dt><dd>{r.centroid.x.toFixed(3)}, {r.centroid.y.toFixed(3)} m · {formatLength(r.centroid.z, u)}</dd>
        <dt className="text-muted-foreground">Peak</dt><dd>{r.peak_location.x.toFixed(3)}, {r.peak_location.y.toFixed(3)} m · {formatLength(r.peak_location.z, u)}</dd>
        <dt className="text-muted-foreground">Bounds x</dt><dd>{r.bounds.x_min.toFixed(3)} – {r.bounds.x_max.toFixed(3)} m</dd>
        <dt className="text-muted-foreground">Bounds y</dt><dd>{r.bounds.y_min.toFixed(3)} – {r.bounds.y_max.toFixed(3)} m</dd>
        <dt className="text-muted-foreground">Bounds z</dt><dd>{formatLength(r.bounds.z_min, u)} – {formatLength(r.bounds.z_max, u)}</dd>
        <dt className="text-muted-foreground">Extent</dt><dd>{formatLength(r.physical_extent.x, 'm')} × {formatLength(r.physical_extent.y, 'm')} × {formatLength(r.physical_extent.z, u)}</dd>
        <dt className="text-muted-foreground">FWHM</dt><dd>{formatLength(r.fwhm.x, 'm')} × {formatLength(r.fwhm.y, 'm')} × {formatLength(r.fwhm.z, u)}</dd>
        <dt className="text-muted-foreground">Voxels / lines</dt><dd>{r.voxel_count.toLocaleString()} · {r.lines_spanned} lines</dd>
        <dt className="text-muted-foreground">Shape</dt><dd>elongation {r.shape.elongation.toFixed(1)}{r.shape.azimuth_deg != null ? ` · azimuth ${r.shape.azimuth_deg.toFixed(0)}° · dip ${r.shape.dip_deg?.toFixed(0)}°` : ''}</dd>
        <dt className="text-muted-foreground">Peak response</dt><dd>{ev?.peak_value.toPrecision(4)} {ev?.unit} · robust z {ev?.peak_robust_z.toFixed(1)} · contrast {ev?.peak_local_contrast.toFixed(1)}</dd>
        <dt className="text-muted-foreground">Evidence score</dt><dd>{r.evidence_score.toFixed(2)} <span className="text-muted-foreground">(response quality, not a probability)</span></dd>
        <dt className="text-muted-foreground">Components</dt><dd>{Object.entries(r.score_components).map(([k, v]) => `${k.replace(/_/g, ' ')} ${v.toFixed(2)}`).join(' · ')}</dd>
      </dl>
      <div data-testid="region-support">
        <p className="font-medium">Support</p>
        <p>measured {pct(r.support.measured_voxel_fraction)} · reconstructed {pct(r.support.reconstructed_voxel_fraction)} · interpolated {pct(r.support.interpolated_voxel_fraction)} · unsupported {pct(r.support.unsupported_voxel_fraction)}</p>
        <p className="text-muted-foreground">peak voxel: {r.support.peak_support_class.toLowerCase()} · nearest measurement ≤ {formatLength(r.support.nearest_measurement_distance_m.max ?? 0, 'm')}</p>
        {r.flags.length > 0 && <p className="text-amber-500">{r.flags.join(' · ')}</p>}
      </div>
      {r.generation && (
        <p className="text-muted-foreground" data-testid="region-generation">
          Generated by {r.generation.algorithm} {r.generation.version} ({r.generation.migrated_volume ? 'migrated volume' : 'unmigrated'}): {r.generation.threshold_method}
        </p>
      )}
      <div className="space-y-1 border-t border-border pt-1.5" data-testid="region-review">
        <p className="font-medium">Is this a genuine subsurface response worth retaining?</p>
        <p data-testid="region-review-status">Current: <b>{r.review.status.replace(/_/g, ' ')}</b>{r.review.reviewer_id ? ` by ${r.review.reviewer_id}` : ''}</p>
        <input aria-label="review notes" placeholder="notes (optional)" value={notes} onChange={(e) => setNotes(e.target.value)}
          className="w-full rounded border border-border bg-background px-1" />
        <div className="flex flex-wrap gap-1.5">
          {(Object.keys(REVIEW_LABEL) as Exclude<RegionReviewStatus, 'unreviewed'>[]).map((s) => (
            <Button key={s} size="xs" variant="outline" disabled={busy} onClick={() => onReview(s)}>{REVIEW_LABEL[s]}</Button>
          ))}
        </div>
        {(r.review_history ?? []).length > 0 && (
          <ol className="space-y-0.5 text-muted-foreground" data-testid="region-review-history">
            {(r.review_history ?? []).map((h, n) => (
              <li key={n}>{h.timestamp?.slice(0, 19).replace('T', ' ')} · {h.reviewer_id} · {h.status.replace(/_/g, ' ')}{h.notes ? ` — ${h.notes}` : ''}</li>
            ))}
          </ol>
        )}
        <p className="text-muted-foreground">Operator evidence (grade C), never ground truth. No object class is asked for or recorded.</p>
      </div>
    </div>
  )
}
