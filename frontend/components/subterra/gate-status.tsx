import { Lock, ShieldCheck } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { GateStatus, OpenQuestion } from '@/types/subterra'

/**
 * An evidence gate, rendered with its status intact.
 *
 * `benchmark/gates.py` exists so that "a claim the evidence does not
 * support cannot be made by accident later". Two gates are currently
 * BLOCKED: BAM localisation ("absolute origin is not verified") and 4TU
 * object-level scoring ("4TU publishes no trench coordinates").
 *
 * This component's whole job is to make that visible and unmissable. A
 * BLOCKED gate is rendered prominently, with the backend's reason verbatim
 * — never softened, never hidden behind a disclosure, and never implied to
 * be resolved because some *other* metric happens to be available.
 */
export function BlockedGate({
  label,
  status,
  reason,
  className,
}: {
  /** What the gate governs, e.g. "Localisation scoring". */
  label: string
  status: GateStatus | string
  /** The backend's blocked reason, rendered verbatim. */
  reason?: string | null
  className?: string
}) {
  const blocked = status !== 'RESOLVED'
  const Icon = blocked ? Lock : ShieldCheck

  return (
    <div
      data-gate={label}
      data-gate-status={status}
      className={cn(
        'rounded-lg border px-3.5 py-3',
        blocked
          ? 'subterra-hatch border-destructive/45 bg-destructive/5'
          : 'border-success/35 bg-success/5',
        className,
      )}
    >
      <div className="flex items-start gap-2.5">
        <Icon
          aria-hidden
          className={cn(
            'mt-0.5 size-4 shrink-0',
            blocked ? 'text-destructive' : 'text-success',
          )}
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <span className="text-sm font-medium text-foreground">{label}</span>
            <span
              className={cn(
                'rounded px-1.5 py-px font-mono text-[11px] font-semibold tracking-wider',
                blocked
                  ? 'bg-destructive/15 text-destructive'
                  : 'bg-success/15 text-success',
              )}
            >
              {status}
            </span>
          </div>
          {reason && (
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
              {reason}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}

/**
 * The unresolved evidence questions behind a gate.
 *
 * Carried forward verbatim from the acquisition assessment "so they cannot
 * be quietly dropped" — so this renders all of them, with no truncation and
 * no "show more" that would let one go unread.
 */
export function OpenQuestions({
  questions,
  className,
}: {
  /** Either full question records, or the id list an artifact carries. */
  questions: (OpenQuestion | string)[]
  className?: string
}) {
  if (questions.length === 0) return null

  return (
    <ul className={cn('space-y-2', className)}>
      {questions.map((q) => {
        const id = typeof q === 'string' ? q : q.id
        return (
          <li
            key={id}
            className="rounded-lg border border-border px-2.5 py-2 text-xs"
          >
            <code className="font-mono text-[11px] text-warning">{id}</code>
            {typeof q !== 'string' && (
              <div className="mt-1.5 space-y-1 text-muted-foreground">
                <p className="leading-relaxed">{q.statement}</p>
                <p className="leading-relaxed">
                  <span className="text-foreground">Blocks:</span> {q.blocks}
                </p>
                <p className="leading-relaxed">
                  <span className="text-foreground">Resolution:</span>{' '}
                  {q.resolution_route}
                </p>
              </div>
            )}
          </li>
        )
      })}
    </ul>
  )
}

/**
 * A scope statement.
 *
 * `benchmark/gates.py` keeps these in code specifically so "a report cannot
 * be written without it" — e.g. BAM results "are not evidence of
 * soil/utility-scale subsurface detection or localisation performance".
 * Wherever a number from an artifact is shown, its scope is shown with it.
 */
export function ScopeStatement({
  scope,
  className,
}: {
  scope: string
  className?: string
}) {
  return (
    <p
      className={cn(
        'border-l-2 border-warning/50 bg-warning/5 py-2 pl-3 pr-2 text-xs leading-relaxed text-muted-foreground',
        className,
      )}
    >
      <span className="font-medium text-warning">Scope. </span>
      {scope}
    </p>
  )
}
