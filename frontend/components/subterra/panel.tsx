import { cn } from '@/lib/utils'

/**
 * Workspace panel primitives.
 *
 * The v0 design's card rhythm, adapted for a dense three-pane analysis
 * workspace rather than a marketing page: tighter padding, an uppercase
 * section eyebrow matching the thin client's `h2` treatment, and an
 * optional count chip.
 */

export function Panel({
  className,
  children,
  ...props
}: React.ComponentProps<'section'>) {
  return (
    <section
      className={cn(
        'flex min-h-0 flex-col overflow-hidden rounded-xl bg-card ring-1 ring-foreground/10',
        className,
      )}
      {...props}
    >
      {children}
    </section>
  )
}

export function PanelHeader({
  title,
  count,
  action,
  className,
}: {
  title: string
  count?: number | null
  action?: React.ReactNode
  className?: string
}) {
  return (
    <header
      className={cn(
        'flex shrink-0 items-center justify-between gap-2 border-b border-border px-3.5 py-2.5',
        className,
      )}
    >
      <div className="flex items-baseline gap-2">
        <h2 className="text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
          {title}
        </h2>
        {count !== undefined && count !== null && (
          <span className="tabular rounded border border-border px-1 font-mono text-[10px] text-muted-foreground">
            {count}
          </span>
        )}
      </div>
      {action}
    </header>
  )
}

export function PanelBody({
  className,
  children,
  ...props
}: React.ComponentProps<'div'>) {
  return (
    <div className={cn('min-h-0 flex-1 overflow-y-auto p-3.5', className)} {...props}>
      {children}
    </div>
  )
}

/** A label/value row for detail panels. Absent values arrive pre-formatted. */
export function Field({
  label,
  children,
  className,
}: {
  label: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn('grid grid-cols-[minmax(0,7rem)_1fr] gap-2 py-1', className)}>
      <dt className="text-xs leading-relaxed text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-xs leading-relaxed text-foreground">{children}</dd>
    </div>
  )
}

/**
 * A section eyebrow used inside scrolling sidebars, matching the thin
 * client's `h2 { text-transform: uppercase; letter-spacing: .06em }`.
 */
export function SectionLabel({
  children,
  count,
  className,
}: {
  children: React.ReactNode
  count?: number | null
  className?: string
}) {
  return (
    <div className={cn('flex items-baseline gap-2 pb-1.5 pt-4 first:pt-0', className)}>
      <h3 className="text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
        {children}
      </h3>
      {count !== undefined && count !== null && (
        <span className="tabular rounded border border-border px-1 font-mono text-[10px] text-muted-foreground">
          {count}
        </span>
      )}
    </div>
  )
}
