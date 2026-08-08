import Link from 'next/link'
import { SubterraLogo } from '@/components/brand/logo'
import { buttonVariants } from '@/components/ui/button'

/**
 * The instrument bar.
 *
 * Every link points at a route that exists. There is no Pricing, Docs,
 * Customers or Blog entry, because none of those exist and a link to a page
 * that does not exist is a claim about the product.
 */
export function LandingNav() {
  return (
    <header className="fixed inset-x-0 top-0 z-30 border-b border-border/50 bg-background/70 backdrop-blur-md">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-5 py-3 sm:px-8">
        <Link
          href="/"
          className="min-w-0 rounded-lg outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          aria-label="Subterra home"
        >
          <SubterraLogo size="sm" className="sm:hidden" />
          <SubterraLogo className="hidden sm:inline-flex" />
        </Link>

        {/*
         * The nav collapses by SHORTENING rather than hiding: at 390px the
         * full set measured 411px wide and clipped the CTA. Below `sm` the
         * secondary link drops to its bare noun and the CTA to one word, which
         * fits 360px with room and keeps both destinations reachable. The
         * benchmark route also remains linked from the closing stage, so no
         * destination depends on this bar.
         */}
        <nav className="flex items-center gap-1 sm:gap-2" aria-label="Primary">
          <Link
            href="/benchmark"
            className={buttonVariants({ variant: 'ghost', size: 'sm' })}
          >
            Benchmarks
          </Link>
          <Link
            href="/datasets"
            className={buttonVariants({ variant: 'default', size: 'sm' })}
          >
            <span className="sm:hidden">Workspace</span>
            <span className="hidden sm:inline">Open workspace</span>
          </Link>
        </nav>
      </div>
    </header>
  )
}
