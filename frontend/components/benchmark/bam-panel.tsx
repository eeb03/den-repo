'use client'

import { Panel, PanelBody, PanelHeader } from '@/components/subterra/panel'
import { QueryState } from '@/components/subterra/query-state'
import { StateBox } from '@/components/subterra/state-box'
import {
  BlockedGate,
  OpenQuestions,
  ScopeStatement,
} from '@/components/subterra/gate-status'
import { ProvenanceTag } from '@/components/subterra/provenance-tag'
import { Interpretation, Metric } from './metric'
import { useBenchmarkArtifact } from '@/hooks/use-subterra'
import { formatCount } from '@/lib/format'
import type { BenchmarkArtifactEntry } from '@/types/subterra'

interface PerTarget {
  lines_with_a_match: number
  lines_processed: number
  grid_index: number
  footprint: [number, number]
  target_type: string
  position_provenance: string
}

/**
 * BAM — controlled concrete NDT specimen.
 *
 * Everything rendered comes from artifacts/bam/score_*.json. Nothing is
 * recomputed: the per-target block below is the artifact's own
 * `detection.per_target`, printed.
 */
export function BamPanel({
  artifacts,
  selected,
  onSelect,
}: {
  artifacts: BenchmarkArtifactEntry[]
  selected: string | null
  onSelect: (name: string) => void
}) {
  const { data, error, isLoading } = useBenchmarkArtifact(selected ?? undefined)

  if (artifacts.length === 0) {
    return (
      <Panel>
        <PanelHeader title="BAM — concrete GPR specimen" />
        <PanelBody>
          <StateBox
            kind="empty"
            title="No BAM artifact has been generated"
            detail="Produce one with scripts/score_bam_benchmark.py. Nothing is shown here in the meantime."
          />
        </PanelBody>
      </Panel>
    )
  }

  const detection = (data?.detection ?? {}) as Record<string, unknown>
  const falseAlarms = (data?.false_alarms ?? {}) as Record<string, unknown>
  const perTarget = (detection.per_target ?? {}) as Record<string, PerTarget>
  const grid = (data?.grid ?? {}) as Record<string, unknown>
  const provenance = (data?.provenance ?? {}) as Record<string, unknown>

  const linesProcessed = detection.lines_processed as number | undefined
  const linesAvailable = detection.lines_available as number | undefined
  const partial =
    linesProcessed !== undefined &&
    linesAvailable !== undefined &&
    linesProcessed < linesAvailable

  return (
    <Panel className="min-h-0">
      <PanelHeader
        title="BAM — concrete GPR specimen"
        action={
          <select
            aria-label="BAM scan"
            value={selected ?? ''}
            onChange={(e) => onSelect(e.target.value)}
            className="h-7 rounded-lg border border-border bg-card px-2 text-[11px] text-foreground outline-none"
          >
            {artifacts.map((a) => (
              <option key={a.name} value={a.name}>
                {a.filename.replace(/^score_|\.json$/g, '')}
              </option>
            ))}
          </select>
        }
      />
      <PanelBody className="space-y-3">
        <QueryState
          isLoading={isLoading}
          error={error}
          absenceTitle="BAM artifact unavailable"
          errorTitle="Could not load the BAM artifact"
          skeletonRows={5}
        />

        {data && (
          <>
            {partial && (
              <StateBox
                kind="unavailable"
                title="Partial run — not the full scan"
                detail={`This report scored ${formatCount(linesProcessed)} of ${formatCount(
                  linesAvailable,
                )} available lines. Its metrics are not comparable with a full-scan report.`}
              />
            )}

            {typeof data.scope === 'string' && <ScopeStatement scope={data.scope} />}

            <BlockedGate
              label="Localisation scoring"
              status={data.localization_status ?? 'BLOCKED'}
              reason={data.localization_blocked_reason}
            />
            <p className="text-[11px] leading-relaxed text-muted-foreground">
              Detection and false-alarm scoring are independently executable and
              do not depend on the absolute origin — they ask whether a
              detection falls inside a footprint defined in the same grid the
              detections are indexed by. A blocked localisation gate does not
              make the detection numbers below invalid, and they do not make the
              gate any less blocked.
            </p>

            {/* ------------------------------ identity ---------------------- */}
            <dl>
              <Metric label="Benchmark" value={data.benchmark} />
              <Metric label="Specimen" value={detection.specimen_id as string} />
              <Metric label="Scan" value={detection.scan_id as string} />
              <Metric label="Targets" value={detection.n_targets as number} />
              <Metric label="Lines processed" value={linesProcessed} />
              <Metric
                label="Detector threshold"
                value={data.threshold}
                note={
                  typeof data.parameters_changed_for_this_benchmark === 'string'
                    ? `Parameters changed for this benchmark: ${data.parameters_changed_for_this_benchmark}.`
                    : null
                }
              />
              <Metric label="min_cells" value={data.min_cells} />
            </dl>

            {/* ------------------------------ detection --------------------- */}
            <div>
              <h3 className="pb-1 text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
                Detection
              </h3>
              <dl>
                <Metric label="Recall" value={detection.recall as number} emphasis />
                <Metric label="Precision" value={detection.precision as number} emphasis />
                <Metric label="F1" value={detection.f1 as number} emphasis />
                <Metric label="True positives" value={detection.true_positives as number} />
                <Metric label="False positives" value={detection.false_positives as number} />
                <Metric label="False negatives" value={detection.false_negatives as number} />
                <Metric
                  label="Overlapping any node"
                  value={detection.overlapping_any_node as number}
                  note="The permissive count, reported alongside the strict peak-node rule so the choice of rule is visible rather than buried."
                />
                <Metric label="Counting unit" value={detection.detection_unit as string} />
              </dl>
              {typeof detection.match_rule === 'string' && (
                <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
                  <span className="text-foreground">Match rule.</span>{' '}
                  {detection.match_rule}
                </p>
              )}
            </div>

            {/* ------------------------------ per target -------------------- */}
            <div>
              <h3 className="pb-1 text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
                Per target
              </h3>
              {Object.keys(perTarget).length === 0 ? (
                <StateBox
                  kind="empty"
                  title="No per-target breakdown in this artifact"
                  detail="The report carries no detection.per_target block."
                />
              ) : (
                <>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b border-border text-left text-[10px] uppercase tracking-wider text-muted-foreground">
                          <th className="py-1 pr-2 font-medium">Target</th>
                          <th className="py-1 pr-2 font-medium">Node</th>
                          <th className="py-1 pr-2 font-medium">Footprint</th>
                          <th className="py-1 text-right font-medium">
                            Lines with a match
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(perTarget).map(([id, t]) => (
                          <tr key={id} data-target={id} className="border-b border-border/50">
                            <td className="py-1 pr-2 font-mono text-[11px] text-foreground">
                              {id}
                            </td>
                            <td className="tabular py-1 pr-2 font-mono text-[11px] text-muted-foreground">
                              {String(t.grid_index)}
                            </td>
                            <td className="tabular py-1 pr-2 font-mono text-[11px] text-muted-foreground">
                              {t.footprint?.join('–')}
                            </td>
                            <td className="tabular py-1 text-right font-mono text-[11px] text-foreground">
                              {String(t.lines_with_a_match)} / {String(t.lines_processed)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
                    All four ducts are known to be present — their positions are
                    transcribed from publication and associate to grid nodes with
                    zero residual. A low count here is a{' '}
                    <span className="text-foreground">detector miss</span>, not
                    evidence that the duct is absent.
                  </p>
                  <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                    Target depth is not carried in this artifact, so results are
                    shown by duct rather than by depth. The published centre
                    depths live in{' '}
                    <code className="font-mono">
                      docs/external-gpr-benchmark-acquisition.md
                    </code>
                    .
                  </p>
                </>
              )}
            </div>

            {/* ------------------------------ false alarms ------------------ */}
            {Object.keys(falseAlarms).length > 0 && (
              <div>
                <h3 className="pb-1 text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
                  False alarms — attested-empty control
                </h3>
                <dl>
                  <Metric label="Control specimen" value={falseAlarms.specimen_id as string} />
                  <Metric label="Detections" value={falseAlarms.n_detections as number} />
                  <Metric
                    label="Detections per line"
                    value={falseAlarms.detections_per_line as number}
                    note={falseAlarms.rate_basis as string}
                  />
                  <Metric
                    label="Per-area rate"
                    value={falseAlarms.per_area_rate as number | null}
                    note={falseAlarms.per_area_note as string}
                  />
                </dl>
                {typeof falseAlarms.control_caveat === 'string' && (
                  <div className="mt-1.5 border-l-2 border-warning/50 bg-warning/5 py-1.5 pl-2.5 pr-2 text-[11px] leading-relaxed text-muted-foreground">
                    <span className="font-medium text-warning">Caveat. </span>
                    {falseAlarms.control_caveat}
                  </div>
                )}
              </div>
            )}

            {/* ---------------------------- interpretation ------------------ */}
            <Interpretation
              title="Why the detector scores this way"
              source="docs/bam-benchmark-detection.md §4"
            >
              <p>
                The detector performs poorly on this benchmark. Recall
                0.065–0.093 means it misses the great majority of target
                crossings, and precision 0.135–0.147 means most of what it
                reports is not at a target.
              </p>
              <p>
                This is consistent with a limitation measured before this
                benchmark existed: the ring z-score{' '}
                <span className="text-foreground">saturates with target width</span>
                , so a broad, laterally coherent target scores no higher than a
                narrow one and can sit below |z| ≥ 3 regardless of contrast. A
                tendon duct spanning the full specimen width is precisely that
                kind of target. The benchmark did not discover a new problem; it
                put a number on a known one.
              </p>
              <p>
                No threshold was changed in response to these results, and none
                should be. Tuning against the only target truth the project
                holds would convert the benchmark from a measurement into a fit.
              </p>
            </Interpretation>

            <Interpretation
              title="What these numbers do and do not support"
              source="docs/bam-benchmark-detection.md §4"
            >
              <p>
                <span className="text-foreground">Supported:</span> that the
                pipeline runs end to end against real target ground truth; that
                detection and false-alarm rates are now measurable; and a
                baseline to improve against.
              </p>
              <p>
                <span className="text-foreground">Not supported:</span> any claim
                about soil or utility performance, and any localisation claim at
                all.
              </p>
            </Interpretation>

            {/* ------------------------------ grid + provenance ------------- */}
            <div>
              <h3 className="pb-1 text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
                Frame and units
              </h3>
              <dl>
                <Metric label="Frame" value={grid.frame as string} />
                <Metric label="Units X/Y" value={grid.units_xy as string} />
                <Metric label="Units Z" value={grid.units_z as string} />
                <Metric label="CRS" value={(grid.crs as string) ?? null} />
                <Metric
                  label="Absolute origin verified"
                  value={String(grid.absolute_origin_verified)}
                />
              </dl>
              <div className="mt-1.5 flex flex-wrap items-center gap-2">
                <span className="text-[11px] text-muted-foreground">units:</span>
                <ProvenanceTag
                  provenance={grid.units_provenance as string}
                  basis="how the millimetre unit for X/Y was established"
                  size="sm"
                />
                <span className="text-[11px] text-muted-foreground">CRS:</span>
                <ProvenanceTag
                  provenance={grid.crs_provenance as string}
                  size="sm"
                />
              </div>
            </div>

            <div>
              <h3 className="pb-1 text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
                Source provenance
              </h3>
              <dl>
                <Metric label="DOI" value={provenance.doi as string} />
                <Metric label="Repository" value={provenance.repository as string} />
                <Metric label="Licence" value={provenance.licence as string} />
                <Metric label="Archive" value={provenance.archive as string} />
                <Metric
                  label="Archive MD5 verified"
                  value={String(provenance.archive_md5_verified)}
                />
                <Metric
                  label="Source files unmodified"
                  value={String(provenance.source_files_unmodified)}
                />
              </dl>
            </div>

            {Array.isArray(data.open_questions) && data.open_questions.length > 0 && (
              <div>
                <h3 className="pb-1 text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
                  Open questions ({data.open_questions.length})
                </h3>
                <OpenQuestions questions={data.open_questions} />
              </div>
            )}
          </>
        )}
      </PanelBody>
    </Panel>
  )
}
