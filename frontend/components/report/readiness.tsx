import { cn } from '@/lib/utils'
import type { Capability, CapabilityAssessment, Readiness } from '@/types/subterra'

/**
 * How a capability's state is drawn.
 *
 * THE THREE STATES MUST NOT LOOK ALIKE, and BLOCKED must not look like an
 * error. A blocked capability is not a fault in the platform or in the user's
 * file -- it is a statement that the evidence required does not exist. Drawing
 * it in the same red as a failed request would teach people to read a correct,
 * important answer as something broken that somebody will fix.
 *
 * So: ready is affirmative, partial is qualified, blocked is stated plainly in
 * the foreground colour with a hatched marker. None of them is red.
 */
const READINESS_STYLE: Record<Readiness, { label: string; dot: string; text: string }> = {
  ready: {
    label: 'Ready',
    dot: 'bg-primary',
    text: 'text-foreground',
  },
  partial: {
    label: 'Partial',
    dot: 'bg-primary/40 ring-1 ring-primary/60',
    text: 'text-foreground',
  },
  blocked: {
    label: 'Blocked',
    dot: 'border border-muted-foreground/60 bg-transparent',
    text: 'text-muted-foreground',
  },
}

export const CAPABILITY_LABEL: Record<Capability, string> = {
  ingestion: 'Ingestion',
  validation: 'Validation',
  signal_processing: 'Signal processing',
  horizontal_registration: 'Horizontal registration',
  vertical_registration: 'Vertical reconstruction',
  candidate_analysis: 'Candidate analysis',
  object_classification: 'Object classification',
  reconstruction_3d: '3D reconstruction',
}

export function ReadinessBadge({ readiness }: { readiness: Readiness }) {
  const style = READINESS_STYLE[readiness]
  return (
    <span
      data-readiness={readiness}
      className="inline-flex shrink-0 items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground"
    >
      <span className={cn('size-1.5 rounded-full', style.dot)} aria-hidden="true" />
      {style.label}
    </span>
  )
}

/**
 * One capability, its state, its reason, and — when it is not ready — exactly
 * what would have to be obtained.
 *
 * THE `missing` LIST IS NOT DECORATION. It is the difference between "3D
 * reconstruction is blocked" (which reads as a limitation of the product) and
 * "3D reconstruction is blocked because no frame declares a vertical datum and
 * the depth axis origin is not the ground surface" (which reads as a task).
 * The backend refuses to emit a non-ready state without one.
 */
export function CapabilityRow({ assessment }: { assessment: CapabilityAssessment }) {
  const style = READINESS_STYLE[assessment.readiness]
  return (
    <div
      data-capability={assessment.capability}
      data-readiness={assessment.readiness}
      className="border-t border-border py-3 first:border-t-0"
    >
      <div className="flex items-baseline justify-between gap-3">
        <h4 className={cn('text-sm font-medium', style.text)}>
          {CAPABILITY_LABEL[assessment.capability]}
        </h4>
        <ReadinessBadge readiness={assessment.readiness} />
      </div>

      <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
        {assessment.reason}
      </p>

      {assessment.missing.length > 0 && (
        <div className="mt-2.5">
          <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
            Requires
          </p>
          <ul className="mt-1 space-y-1">
            {assessment.missing.map((item) => (
              <li
                key={item}
                data-missing
                className="flex gap-2 text-xs leading-relaxed text-muted-foreground"
              >
                <span aria-hidden="true" className="select-none text-primary">
                  &middot;
                </span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
