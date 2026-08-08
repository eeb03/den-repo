import { ExternalLink } from 'lucide-react'
import { cn } from '@/lib/utils'

/**
 * Workspace header.
 *
 * Carries the page title and links to the two existing UIs, which remain
 * fully functional and authoritative: `/viewer` (the Plotly 3D / point
 * cloud / heatmap / B-scan viewer) and `/client` (the thin client this
 * workspace's information architecture is modelled on).
 *
 * Deliberately absent: a live status pill, a notification bell, an operator
 * avatar. The platform has no telemetry, no notification service and no
 * auth; each of those controls would assert a capability that does not
 * exist.
 */
export function AppHeader({
  title,
  subtitle,
  actions,
  className,
}: {
  title: string
  subtitle?: string
  actions?: React.ReactNode
  className?: string
}) {
  return (
    <header
      className={cn(
        'flex h-14 shrink-0 items-center justify-between gap-4 border-b border-border px-5',
        className,
      )}
    >
      <div className="min-w-0">
        <h1 className="truncate text-sm font-medium text-foreground">{title}</h1>
        {subtitle && (
          <p className="truncate text-xs leading-relaxed text-muted-foreground">
            {subtitle}
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-1">
        {actions}
        <LegacyLink href="/client" label="Thin client" />
        <LegacyLink href="/viewer" label="3D viewer" />
      </div>
    </header>
  )
}

function LegacyLink({ href, label }: { href: string; label: string }) {
  return (
    <a
      href={href}
      className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
    >
      {label}
      <ExternalLink className="size-3" aria-hidden />
    </a>
  )
}
