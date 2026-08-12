'use client'

import { cn } from '@/lib/utils'
import type { ImportJob, ImportStage } from '@/types/subterra'

/**
 * Where the import has got to.
 *
 * A STAGE TRACK, NOT A PROGRESS BAR. The ingest pipeline reports which step it
 * is in; it cannot report how far through that step it is, and a bar filled to
 * some fraction of five steps would be a number the platform invented. So the
 * steps are listed and the current one is marked. A reader learns exactly what
 * is known -- which stage -- and is told nothing that is not.
 *
 * The stage names are the pipeline's own, passed through the job record from
 * `_run_ingest_pipeline`'s `on_stage` hook.
 */
const STAGES: { id: ImportStage; label: string; detail: string }[] = [
  { id: 'queued', label: 'Queued', detail: 'Waiting for the import worker' },
  { id: 'converting', label: 'Converting', detail: 'Reading the file with its format adapter' },
  { id: 'validating', label: 'Validating', detail: 'Coordinate, range and signal checks' },
  { id: 'preprocessing', label: 'Preprocessing', detail: 'Trace-domain pipeline' },
  { id: 'persisting', label: 'Persisting', detail: 'Writing records and the survey frame' },
  { id: 'registering', label: 'Registering', detail: 'Creating the dataset entry' },
  { id: 'complete', label: 'Complete', detail: 'Dataset available in the workspace' },
]

const STATE_TONE: Record<string, string> = {
  QUEUED: 'text-muted-foreground border-border',
  RUNNING: 'text-primary border-primary/40',
  SUCCEEDED: 'text-prov-measured border-prov-measured/40',
  FAILED: 'text-destructive border-destructive/40',
}

export function JobState({ job }: { job: ImportJob }) {
  return (
    <span
      data-job-state={job.state}
      className={cn(
        'inline-flex items-center gap-2 rounded-md border px-2 py-1 font-mono text-[11px] uppercase tracking-[0.16em]',
        STATE_TONE[job.state] ?? 'text-muted-foreground border-border',
      )}
    >
      {job.state === 'RUNNING' && (
        <span aria-hidden className="size-1.5 animate-pulse rounded-full bg-primary" />
      )}
      {job.state}
    </span>
  )
}

export function StageTrack({ job }: { job: ImportJob }) {
  const currentIndex = STAGES.findIndex((s) => s.id === job.stage)
  const failed = job.state === 'FAILED'

  return (
    <ol data-stage-track className="space-y-px">
      {STAGES.map((stage, i) => {
        const isCurrent = i === currentIndex && !failed
        const isDone = currentIndex > i || job.state === 'SUCCEEDED'
        return (
          <li
            key={stage.id}
            data-stage={stage.id}
            data-stage-active={isCurrent}
            className={cn(
              'flex items-baseline gap-3 border-l-2 py-1.5 pl-3.5 transition-colors',
              isCurrent
                ? 'border-primary'
                : isDone
                  ? 'border-prov-measured/50'
                  : 'border-border/60',
            )}
          >
            <span
              className={cn(
                'w-24 shrink-0 font-mono text-[11px] uppercase tracking-[0.16em]',
                isCurrent
                  ? 'text-primary'
                  : isDone
                    ? 'text-foreground/70'
                    : 'text-muted-foreground/40',
              )}
            >
              {stage.label}
            </span>
            <span
              className={cn(
                'text-xs leading-relaxed',
                isCurrent ? 'text-muted-foreground' : 'text-muted-foreground/50',
              )}
            >
              {stage.detail}
            </span>
          </li>
        )
      })}
    </ol>
  )
}
