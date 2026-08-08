'use client'

import { useState } from 'react'
import { AppHeader } from '@/components/shell/app-header'
import { Panel, PanelBody, PanelHeader } from '@/components/subterra/panel'
import { QueryState } from '@/components/subterra/query-state'
import { StateBox } from '@/components/subterra/state-box'
import {
  BlockedGate,
  OpenQuestions,
  ScopeStatement,
} from '@/components/subterra/gate-status'
import { useBenchmarkArtifact, useBenchmarkArtifacts } from '@/hooks/use-subterra'
import { formatCount } from '@/lib/format'
import type { BenchmarkArtifact } from '@/types/subterra'

/**
 * Benchmark workspace.
 *
 * Reads `GET /api/benchmark/artifacts`, which serves the scoring artifacts
 * verbatim. NOTHING on this page recomputes, rescales, rounds or
 * reinterprets a figure: every number rendered is `String(value)` of what
 * the artifact holds, so a reader sees the recorded value and not a
 * presentation of it.
 *
 * Gate statuses are rendered as they are stored. BAM localisation is
 * BLOCKED on an unverified absolute origin and 4TU object-level scoring is
 * BLOCKED on absent trench coordinates; both are shown prominently, with
 * the scope statement that `benchmark/gates.py` keeps in code precisely so
 * that a report cannot be written without it.
 */
export default function BenchmarkPage() {
  const { data, error, isLoading } = useBenchmarkArtifacts()
  const [selected, setSelected] = useState<string | null>(null)

  const artifacts = data?.artifacts ?? []
  const active = selected ?? artifacts[0]?.name ?? null

  return (
    <>
      <AppHeader
        title="Benchmark"
        subtitle="Evaluation results, shown exactly as the platform records them"
      />
      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        <div className="mx-auto max-w-4xl space-y-3">
          <QueryState
            isLoading={isLoading}
            error={error}
            absenceTitle="Benchmark artifacts unavailable"
            errorTitle="Could not list benchmark artifacts"
            skeletonRows={3}
          />

          {data && artifacts.length === 0 && (
            <StateBox
              kind="empty"
              title="No benchmark artifacts have been generated"
              detail={
                data.note ??
                'Artifacts are produced by the scoring scripts under scripts/ and are regenerable. None is present.'
              }
            />
          )}

          {artifacts.length > 0 && (
            <>
              <nav className="flex flex-wrap gap-1.5" aria-label="Artifacts">
                {artifacts.map((entry) => (
                  <button
                    key={entry.name}
                    type="button"
                    onClick={() => setSelected(entry.name)}
                    aria-current={entry.name === active ? 'true' : undefined}
                    className={`rounded-lg border px-2.5 py-1.5 text-xs transition-colors ${
                      entry.name === active
                        ? 'border-primary/50 bg-primary/10 text-foreground'
                        : 'border-border text-muted-foreground hover:border-primary/30 hover:text-foreground'
                    }`}
                  >
                    <span className="font-mono">{entry.name}</span>
                    <span className="ml-1.5 text-[10px] text-muted-foreground">
                      {(entry.size_bytes / 1024).toFixed(0)} kB
                    </span>
                  </button>
                ))}
              </nav>

              {active && <ArtifactView name={active} />}
            </>
          )}
        </div>
      </div>
    </>
  )
}

function ArtifactView({ name }: { name: string }) {
  const { data, error, isLoading } = useBenchmarkArtifact(name)

  return (
    <>
      <QueryState
        isLoading={isLoading}
        error={error}
        absenceTitle="Artifact unavailable"
        errorTitle="Could not load the artifact"
        skeletonRows={4}
      />
      {data && <ArtifactBody name={name} artifact={data} />}
    </>
  )
}

function ArtifactBody({
  name,
  artifact,
}: {
  name: string
  artifact: BenchmarkArtifact
}) {
  const gates = [
    {
      label: 'Localisation scoring',
      status: artifact.localization_status,
      reason: artifact.localization_blocked_reason,
    },
    {
      label: 'Object-level scoring',
      status: artifact.object_level_status,
      reason: artifact.object_level_blocked_reason,
    },
    {
      label: 'Activity-level scoring',
      status: artifact.activity_level_status,
      reason: null,
    },
  ].filter((g) => g.status)

  return (
    <div className="space-y-3">
      <Panel>
        <PanelHeader
          title={artifact.benchmark ?? name}
          action={
            <span className="font-mono text-[11px] text-muted-foreground">
              {name}
            </span>
          }
        />
        <PanelBody className="space-y-3">
          {artifact.scope && <ScopeStatement scope={artifact.scope} />}

          {gates.length > 0 && (
            <div className="space-y-2">
              {gates.map((gate) => (
                <BlockedGate
                  key={gate.label}
                  label={gate.label}
                  status={gate.status as string}
                  reason={gate.reason}
                />
              ))}
            </div>
          )}

          {(artifact.threshold !== undefined ||
            artifact.parameters_changed_for_this_benchmark) && (
            <p className="text-xs leading-relaxed text-muted-foreground">
              {artifact.threshold !== undefined && (
                <>
                  Detector run at threshold{' '}
                  <span className="tabular font-mono text-foreground">
                    {String(artifact.threshold)}
                  </span>
                  {artifact.min_cells !== undefined && (
                    <>
                      , min_cells{' '}
                      <span className="tabular font-mono text-foreground">
                        {String(artifact.min_cells)}
                      </span>
                    </>
                  )}
                  .{' '}
                </>
              )}
              {artifact.parameters_changed_for_this_benchmark && (
                <>
                  Parameters changed for this benchmark:{' '}
                  <span className="font-mono text-foreground">
                    {String(artifact.parameters_changed_for_this_benchmark)}
                  </span>
                  .
                </>
              )}
            </p>
          )}
        </PanelBody>
      </Panel>

      {artifact.detection && (
        <Panel>
          <PanelHeader title="Detection" />
          <PanelBody>
            <MetricGrid source={artifact.detection} />
          </PanelBody>
        </Panel>
      )}

      {artifact.score && (
        <Panel>
          <PanelHeader title="Score" />
          <PanelBody>
            <MetricGrid source={artifact.score} />
          </PanelBody>
        </Panel>
      )}

      {artifact.open_questions && artifact.open_questions.length > 0 && (
        <Panel>
          <PanelHeader
            title="Open questions"
            count={artifact.open_questions.length}
          />
          <PanelBody>
            <p className="mb-2 text-xs leading-relaxed text-muted-foreground">
              Unresolved evidence questions, carried forward verbatim so they
              cannot be quietly dropped.
            </p>
            <OpenQuestions questions={artifact.open_questions} />
          </PanelBody>
        </Panel>
      )}

      {artifact.provenance && (
        <Panel>
          <PanelHeader title="Provenance" />
          <PanelBody>
            <MetricGrid source={artifact.provenance} />
          </PanelBody>
        </Panel>
      )}

      {artifact.grid && (
        <Panel>
          <PanelHeader title="Grid" />
          <PanelBody>
            <MetricGrid source={artifact.grid} />
          </PanelBody>
        </Panel>
      )}
    </div>
  )
}

/**
 * Renders an artifact section as label/value rows.
 *
 * Scalars are printed with `String(value)` — no rounding, no percentage
 * conversion, no unit inference. A recall of 0.06521739130434782 is shown
 * as recorded; presenting it as "6.5%" would be a transformation of a
 * scientific result, however harmless it looks.
 *
 * Nested objects are shown as formatted JSON rather than being flattened or
 * summarised, so nothing is dropped on the way to the screen.
 */
function MetricGrid({ source }: { source: Record<string, unknown> }) {
  const entries = Object.entries(source)
  return (
    <dl className="space-y-1">
      {entries.map(([key, value]) => {
        const isScalar =
          value === null || ['string', 'number', 'boolean'].includes(typeof value)
        return (
          <div
            key={key}
            className="grid grid-cols-[minmax(0,14rem)_1fr] gap-3 border-b border-border/60 py-1.5 last:border-0"
          >
            <dt className="font-mono text-[11px] leading-relaxed text-muted-foreground">
              {key}
            </dt>
            <dd className="min-w-0 text-xs leading-relaxed text-foreground">
              {isScalar ? (
                <span className="tabular font-mono break-all">
                  {value === null ? 'null' : String(value)}
                </span>
              ) : Array.isArray(value) && value.every((v) => typeof v === 'string') ? (
                <span className="font-mono break-all">
                  {(value as string[]).join(', ')}
                </span>
              ) : (
                <details>
                  <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
                    {Array.isArray(value)
                      ? `${formatCount(value.length)} entries`
                      : `${formatCount(Object.keys(value as object).length)} fields`}
                  </summary>
                  <pre className="mt-1.5 max-h-64 overflow-auto rounded border border-border bg-background/60 p-2 font-mono text-[10px] leading-relaxed">
                    {JSON.stringify(value, null, 2)}
                  </pre>
                </details>
              )}
            </dd>
          </div>
        )
      })}
    </dl>
  )
}
