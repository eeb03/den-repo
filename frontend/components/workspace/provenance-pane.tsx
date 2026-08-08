'use client'

import { SectionLabel } from '@/components/subterra/panel'
import { QueryState } from '@/components/subterra/query-state'
import { StateBox } from '@/components/subterra/state-box'
import { ProvenanceTag } from '@/components/subterra/provenance-tag'
import { useFrameProvenance } from '@/hooks/use-subterra'

/**
 * Per-frame provenance, from `GET /api/provenance/{id}/frames`.
 *
 * Each entry is one `QuantityProvenance`: a quantity, its class, and the
 * `basis` sentence justifying that class. `schemas/provenance.py` requires
 * a non-empty basis specifically so "a provenance label with no
 * justification is decoration" -- so the basis is always rendered next to
 * the tag, never hidden behind a tooltip alone.
 *
 * This is where a reader sees that, for instance, a CRS was *inferred*
 * from stored record positions rather than *declared by the source*, or
 * that a vertical datum is simply `unavailable`.
 */
export function ProvenancePane({ datasetId }: { datasetId: string }) {
  const { data, error, isLoading } = useFrameProvenance(datasetId)

  return (
    <>
      <SectionLabel count={data?.frame_count}>Provenance</SectionLabel>
      <QueryState
        isLoading={isLoading}
        error={error}
        absenceTitle="Provenance unavailable"
        errorTitle="Could not load provenance"
      />
      {data &&
        (data.frames.length === 0 ? (
          <StateBox
            kind="empty"
            title="No frames"
            detail="This dataset has no survey frames to report provenance for."
          />
        ) : (
          <div className="space-y-2.5">
            {data.frames.map((frame) => (
              <div
                key={frame.frame_id}
                className="rounded-lg border border-border px-2.5 py-2"
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-xs font-medium text-foreground">
                    {frame.modality}
                  </span>
                  <span className="truncate font-mono text-[10px] text-muted-foreground">
                    {frame.source_file ?? frame.source_format ?? 'unknown source'}
                  </span>
                </div>
                <dl className="mt-2 space-y-2">
                  {frame.provenance.map((entry) => (
                    <div key={`${frame.frame_id}:${entry.quantity}`}>
                      <dt className="flex flex-wrap items-center gap-1.5">
                        <span className="font-mono text-[11px] text-foreground">
                          {entry.quantity}
                        </span>
                        <ProvenanceTag
                          provenance={entry.provenance}
                          basis={entry.basis}
                          size="sm"
                        />
                        {entry.value !== null && entry.value !== undefined && (
                          <code className="font-mono text-[10px] text-muted-foreground">
                            {String(entry.value)}
                          </code>
                        )}
                      </dt>
                      <dd className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
                        {entry.basis}
                      </dd>
                    </div>
                  ))}
                </dl>
              </div>
            ))}
          </div>
        ))}
    </>
  )
}
