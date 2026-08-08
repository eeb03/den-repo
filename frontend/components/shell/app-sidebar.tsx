'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  Beaker,
  Database,
  Layers,
  type LucideIcon,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { SubterraLogo } from '@/components/brand/logo'
import { ProvenanceLegend } from '@/components/subterra/provenance-tag'

interface NavItem {
  href: string
  label: string
  icon: LucideIcon
  description: string
}

/**
 * Navigation.
 *
 * Only routes backed by real platform capability appear here. There is no
 * "Sensors", "Fleet", "Alerts" or "Settings" entry, though the v0 design
 * implied all of them: the platform ingests files rather than talking to
 * instruments, and has no telemetry, notification or auth subsystem. An
 * empty nav item for a subsystem that does not exist would be a claim, not
 * a placeholder.
 */
const navItems: NavItem[] = [
  {
    href: '/datasets',
    label: 'Datasets',
    icon: Database,
    description: 'Ingested surveys and their frames',
  },
  {
    href: '/benchmark',
    label: 'Benchmark',
    icon: Beaker,
    description: 'BAM and 4TU evaluation results',
  },
]

export function AppSidebar() {
  const pathname = usePathname()

  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-sidebar-border bg-sidebar">
      <div className="flex h-14 shrink-0 items-center px-4">
        <Link href="/datasets" aria-label="Subterra home">
          <SubterraLogo size="sm" />
        </Link>
      </div>

      <nav className="flex-1 space-y-0.5 px-2.5 py-2" aria-label="Primary">
        {navItems.map((item) => {
          const active =
            pathname === item.href || pathname.startsWith(`${item.href}/`)
          const Icon = item.icon
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? 'page' : undefined}
              className={cn(
                'flex items-start gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors',
                active
                  ? 'bg-sidebar-accent text-sidebar-accent-foreground'
                  : 'text-muted-foreground hover:bg-sidebar-accent/50 hover:text-foreground',
              )}
            >
              <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
              <span className="min-w-0">
                <span className="block font-medium">{item.label}</span>
                <span className="block text-xs leading-relaxed text-muted-foreground">
                  {item.description}
                </span>
              </span>
            </Link>
          )
        })}
      </nav>

      <div className="border-t border-sidebar-border p-3.5">
        <div className="flex items-center gap-1.5 pb-2">
          <Layers className="size-3.5 text-muted-foreground" aria-hidden />
          <h2 className="text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
            Provenance
          </h2>
        </div>
        <ProvenanceLegend />
        <p className="mt-2.5 text-[11px] leading-relaxed text-muted-foreground">
          These are different kinds of doubt, not different amounts. They are
          not ranked.
        </p>
      </div>
    </aside>
  )
}
