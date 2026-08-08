import { cn } from '@/lib/utils'
import {
  AlertTriangle,
  CircleSlash,
  Inbox,
  Lock,
  MapPinOff,
  type LucideIcon,
} from 'lucide-react'

/**
 * The five states, rendered differently and never collapsed.
 *
 * This is a direct port of `stateBox()` from
 * `visualization/thin_client.html`, whose comment reads:
 *
 *   "Empty, unpositioned, unavailable, unassociated and error are five
 *    DIFFERENT states and are rendered differently."
 *
 * and which `tests/test_thin_client.py::
 * test_the_client_distinguishes_the_required_states` enforces. Collapsing
 * any two of them loses information the user needs:
 *
 *   empty          nothing exists            -> nothing to do
 *   unpositioned   exists, has no coordinate -> reachable via the API, not on a map
 *   unavailable    exists, view cannot show it -> the backend said why
 *   unassociated   exists, must not be combined -> composition is not_relatable
 *   error          the request failed        -> retry / a real bug
 *
 * Note that `empty` and `unavailable` in particular must never look alike:
 * "there are no objects" and "there are objects but this view cannot place
 * them" are opposite statements about the data.
 */
export type StateKind =
  | 'empty'
  | 'unpositioned'
  | 'unavailable'
  | 'unassociated'
  | 'error'

const stateStyles: Record<
  StateKind,
  { icon: LucideIcon; border: string; text: string; iconColor: string; hatch: boolean }
> = {
  empty: {
    icon: Inbox,
    border: 'border-border',
    text: 'text-muted-foreground',
    iconColor: 'text-muted-foreground',
    hatch: false,
  },
  unpositioned: {
    icon: MapPinOff,
    border: 'border-prov-unavailable/40',
    text: 'text-muted-foreground',
    iconColor: 'text-prov-unavailable',
    hatch: true,
  },
  unavailable: {
    icon: Lock,
    border: 'border-warning/40',
    text: 'text-foreground',
    iconColor: 'text-warning',
    hatch: true,
  },
  unassociated: {
    icon: CircleSlash,
    border: 'border-prov-inferred/40',
    text: 'text-foreground',
    iconColor: 'text-prov-inferred',
    hatch: true,
  },
  error: {
    icon: AlertTriangle,
    border: 'border-destructive/50',
    text: 'text-destructive',
    iconColor: 'text-destructive',
    hatch: false,
  },
}

export function StateBox({
  kind,
  title,
  detail,
  missing,
  className,
  children,
}: {
  kind: StateKind
  title: string
  /**
   * The backend's own explanation, rendered verbatim. Never write a
   * substitute here for text the API supplied.
   */
  detail?: string | null
  /** The backend's `missing` list, rendered verbatim. */
  missing?: string[]
  className?: string
  children?: React.ReactNode
}) {
  const style = stateStyles[kind]
  const Icon = style.icon
  return (
    <div
      data-state-kind={kind}
      className={cn(
        'rounded-lg border border-dashed px-3.5 py-3 text-sm',
        style.border,
        style.hatch && 'subterra-hatch',
        className,
      )}
    >
      <div className="flex items-start gap-2.5">
        <Icon className={cn('mt-0.5 size-4 shrink-0', style.iconColor)} aria-hidden />
        <div className="min-w-0 flex-1">
          <p className={cn('font-medium', style.text)}>{title}</p>
          {detail && (
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{detail}</p>
          )}
          {missing && missing.length > 0 && (
            <div className="mt-2">
              <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                Missing
              </p>
              <ul className="mt-1 space-y-0.5">
                {missing.map((m) => (
                  <li
                    key={m}
                    className="flex gap-1.5 text-xs leading-relaxed text-muted-foreground"
                  >
                    <span aria-hidden className="text-prov-unavailable">
                      &bull;
                    </span>
                    <span className="font-mono">{m}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {children && <div className="mt-2">{children}</div>}
        </div>
      </div>
    </div>
  )
}
