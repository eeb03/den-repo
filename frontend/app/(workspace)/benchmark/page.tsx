'use client'

import { useMemo, useState } from 'react'
import { AppHeader } from '@/components/shell/app-header'
import { QueryState } from '@/components/subterra/query-state'
import { StateBox } from '@/components/subterra/state-box'
import { BamPanel } from '@/components/benchmark/bam-panel'
import { FourTuPanel } from '@/components/benchmark/fourtu-panel'
import { GroundTruthPanel } from '@/components/benchmark/ground-truth-panel'
import { useBenchmarkArtifacts } from '@/hooks/use-subterra'

/**
 * Benchmark workspace — BAM and 4TU side by side.
 *
 * THIS IS NOT A SCOREBOARD. The two benchmarks measure different things on
 * different material, one of them is a null result, and neither is a target
 * to be improved by the page. They are shown together because the same
 * detector produced both and the same suspected mechanism runs through
 * both, not so that a reader can average them.
 *
 * Accordingly there is no combined score anywhere, no ranking, no
 * pass/fail, no progress indicator, and no comparison of a BAM figure with
 * a 4TU figure. Every number is `String()` of what the artifact holds.
 */
export default function BenchmarkPage() {
  const { data, error, isLoading } = useBenchmarkArtifacts()
  const [bamSelected, setBamSelected] = useState<string | null>(null)

  const artifacts = useMemo(() => data?.artifacts ?? [], [data])

  const bamArtifacts = useMemo(
    () => artifacts.filter((a) => a.group === 'bam'),
    [artifacts],
  )

  /**
   * Prefer a full-scan BAM report over the 20-line probe. Selection is by
   * filename because that is what the artifact listing carries; the panel
   * still checks lines_processed against lines_available and labels a
   * partial run as partial, so this preference is a convenience and not the
   * thing that keeps a partial run from being mistaken for a full one.
   */
  const defaultBam = useMemo(() => {
    const full = bamArtifacts.find((a) => !a.filename.includes('probe'))
    return full?.name ?? bamArtifacts[0]?.name ?? null
  }, [bamArtifacts])

  const fourTu = useMemo(
    () => artifacts.find((a) => a.name === '4tu/benchmark')?.name ?? null,
    [artifacts],
  )

  /*
   * The ground-truth definition. Shown BELOW the scores deliberately: a
   * reader arrives for the numbers, and the question of whether those
   * numbers could have come out differently is what they should leave with.
   */
  const groundTruth = useMemo(
    () => artifacts.find((a) => a.name === 'benchmark/definition')?.name ?? null,
    [artifacts],
  )

  return (
    <>
      <AppHeader
        title="Benchmark"
        subtitle="Frozen baseline — shown exactly as the scoring runs recorded it"
      />
      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        <div className="mx-auto max-w-[110rem] space-y-3">
          <QueryState
            isLoading={isLoading}
            error={error}
            absenceTitle="Benchmark artifacts unavailable"
            errorTitle="Could not list benchmark artifacts"
            skeletonRows={3}
          />

          {data && (
            <>
              <OpenQuestionBanner />

              {artifacts.length === 0 ? (
                <StateBox
                  kind="empty"
                  title="No benchmark artifacts have been generated"
                  detail={
                    data.note ??
                    'Artifacts are produced by the scoring scripts under scripts/ and are regenerable. None is present.'
                  }
                />
              ) : (
                <div className="grid items-start gap-3 xl:grid-cols-2">
                  <BamPanel
                    artifacts={bamArtifacts}
                    selected={bamSelected ?? defaultBam}
                    onSelect={setBamSelected}
                  />
                  <FourTuPanel name={fourTu} />
                  <div className="xl:col-span-2">
                    <GroundTruthPanel name={groundTruth} />
                  </div>
                </div>
              )}

              <NoAggregateNote />
            </>
          )}
        </div>
      </div>
    </>
  )
}

/**
 * The question the baseline exists to answer.
 *
 * Stated at the top so the page reads as evidence about a failure
 * mechanism rather than as a scorecard someone is trying to move.
 */
function OpenQuestionBanner() {
  return (
    <section className="rounded-xl border border-primary/30 bg-primary/5 px-4 py-3">
      <h2 className="text-[11px] font-medium uppercase tracking-[0.08em] text-primary">
        The open question
      </h2>
      <p className="mt-1.5 max-w-4xl text-sm leading-relaxed text-foreground">
        Does an estimator designed to address the measured width-saturation
        failure produce genuinely better subsurface detection{' '}
        <span className="text-primary">at matched false-alarm rate</span>?
      </p>
      <p className="mt-1.5 max-w-4xl text-xs leading-relaxed text-muted-foreground">
        Both benchmarks below are the <span className="text-foreground">frozen
        baseline</span> against which that question would be answered. They
        record where the current detector stands and the evidence for the
        suspected mechanism. Nothing here claims the problem is solved, and a
        higher number is not the goal — a recall improvement bought by
        responding more often is not an improvement at all, which is why the
        false-alarm control travels with the detection figures.
      </p>
    </section>
  )
}

function NoAggregateNote() {
  return (
    <p className="max-w-4xl text-[11px] leading-relaxed text-muted-foreground">
      <span className="text-foreground">No combined score is shown, and none
      should be computed.</span>{' '}
      BAM measures detection against complete truth on a controlled concrete
      specimen; 4TU measures activity-level candidate density against
      trial-trench truth that covers only part of the surveyed ground. They
      have different units, different truth completeness and different scope
      boundaries. Averaging them would produce a number that describes neither
      and licenses claims about both.
    </p>
  )
}
