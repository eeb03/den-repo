import type { Metadata } from 'next'
import { Descent } from '@/components/landing/descent'
import { Bridge } from '@/components/landing/figures/bridge'
import { LandingNav } from '@/components/landing/landing-nav'
import { StageBreak, StageSurface } from '@/components/landing/stages/act-surface'
import { StageCandidate, StageSignal } from '@/components/landing/stages/act-signal'
import {
  StageFrame,
  StageFusion,
  StageProvenance,
} from '@/components/landing/stages/act-space'
import { StageGates, StageView } from '@/components/landing/stages/act-limits'

export const metadata: Metadata = {
  title: 'Subterra — Subsurface Data Platform',
  description:
    'Ingest ground-penetrating radar, terrain models and survey ground truth into one record model, with provenance attached to every value and evidence gates that stay closed until the evidence arrives.',
}

/**
 * THE DESCENT.
 *
 * Nine stages read as one continuous journey from the surface downward and
 * back: surface, break, signal, candidate, frame, fusion, provenance, gates,
 * view. The order is not a narrative device layered over the product -- it is
 * the platform's pipeline, which is why the page can be this dramatic without
 * asserting anything the platform cannot support.
 *
 * ROUTING. This file sits OUTSIDE the `(workspace)` route group, so it renders
 * without the analysis sidebar and cannot inherit workspace layout changes.
 * `/datasets`, `/datasets/[datasetId]` and `/benchmark` are untouched by it.
 *
 * NO DATA. The page fetches nothing. It has no API dependency, so it cannot
 * display a number that looks like a measurement, and it renders identically
 * when the backend is down. Every figure is closed-form geometry captioned as
 * illustrative; the only live facts on the page -- the two blocked gates and
 * the provenance vocabulary -- come from components and tokens the workspace
 * itself uses.
 */
export default function LandingPage() {
  return (
    <>
      <a
        href="#descent"
        className="sr-only rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50"
      >
        Skip to content
      </a>

      <LandingNav />

      <main id="descent" className="bg-background">
        {/*
         * BRIDGES carry a motif across each seam, so the nine stages read as
         * one descent rather than as sections separated by black gaps. Each
         * one shows the departing figure still present while the arriving
         * concept fades up through it. They are quiet by design -- connective
         * tissue, not events.
         */}
        <Descent>
          <StageSurface />
          <StageBreak />
          <Bridge from="contour" to="trace" label="the surface becomes a baseline" />
          <StageSignal />
          <StageCandidate />
          <Bridge from="trace" to="axes" label="traces become coordinates" />
          <StageFrame />
          <Bridge from="axes" to="frames" label="coordinates become frames" />
          <StageFusion />
          <Bridge from="frames" to="chips" label="frames carry provenance" />
          <StageProvenance />
          <Bridge from="chips" to="bars" label="provenance meets its gates" />
          <StageGates />
          <Bridge from="bars" to="panes" label="gates resolve into views" />
          <StageView />
        </Descent>
      </main>
    </>
  )
}
