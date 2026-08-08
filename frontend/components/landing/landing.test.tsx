/**
 * The Descent: what the landing page is not allowed to claim.
 *
 * The landing page is the one surface written to persuade, which makes it the
 * one most likely to drift into a claim the platform cannot support. These
 * tests are about content and structure, not styling -- a restyled stage
 * should not fail here; a stage that grew a fabricated accuracy figure should.
 *
 * They also pin the two properties that make the motion design safe: the
 * geometry is deterministic, and no information is carried by animation alone.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { STAGES } from './descent'
import { LandingNav } from './landing-nav'
import { StageBreak, StageSurface } from './stages/act-surface'
import { StageCandidate, StageSignal } from './stages/act-signal'
import { StageFrame, StageFusion, StageProvenance } from './stages/act-space'
import { StageGates, StageView } from './stages/act-limits'
import { BScanFigure } from './figures/bscan-figure'
import { HeroFigure } from './figures/hero-figure'
import { BreakFigure } from './figures/break-figure'
import { Bridge } from './figures/bridge'
import { FrameFigure } from './figures/frame-figure'

const LANDING_DIR = __dirname
const ROOT = join(LANDING_DIR, '..', '..')

function landingFiles(): string[] {
  const out: string[] = []
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry)
      if (statSync(full).isDirectory()) walk(full)
      else if (/\.tsx?$/.test(full) && !/\.test\.tsx?$/.test(full)) out.push(full)
    }
  }
  walk(LANDING_DIR)
  return out
}

function landingSource(): string {
  const files = landingFiles()
  expect(files.length).toBeGreaterThan(6) // the walker must actually find the page
  return files.map((f) => readFileSync(f, 'utf8')).join('\n')
}

const ALL_STAGES = [
  <StageSurface key="0" />,
  <StageBreak key="1" />,
  <StageSignal key="2" />,
  <StageCandidate key="3" />,
  <StageFrame key="4" />,
  <StageFusion key="5" />,
  <StageProvenance key="6" />,
  <StageGates key="7" />,
  <StageView key="8" />,
]

/** Routes that exist in this app. Anything else linked would be a dead claim. */
const REAL_ROUTES = ['/', '/datasets', '/benchmark']

describe('the nine stages exist and are ordered', () => {
  it('declares exactly nine stages', () => {
    expect(STAGES).toHaveLength(9)
    expect(STAGES.map((s) => s.id)).toEqual([
      'surface', 'break', 'signal', 'candidate', 'frame',
      'fusion', 'provenance', 'gates', 'view',
    ])
  })

  it.each(STAGES.map((s, i) => [i, s.id] as const))(
    'stage %i (%s) renders with its own landmark and index',
    (index, id) => {
      const { container } = render(ALL_STAGES[index]!)
      const section = container.querySelector('[data-stage]')
      expect(section?.getAttribute('data-stage')).toBe(id)
      expect(section?.getAttribute('data-stage-index')).toBe(String(index))
      // every stage is labelled, so the descent is navigable by heading
      expect(container.querySelector(`#${id}-heading`)).toBeTruthy()
    },
  )

  it('descends through depth bands rather than staying flat', () => {
    const depths = STAGES.map((s) => s.depth)
    expect(new Set(depths).size).toBeGreaterThan(2)
    expect(depths[0]).toBe('surface')
    expect(depths[depths.length - 1]).toBe('return')
  })
})

describe('no information depends on motion', () => {
  it('every stage renders its full text with no animation running', () => {
    // jsdom runs no animations at all, so this IS the reduced-motion state.
    for (const [i, stage] of ALL_STAGES.entries()) {
      const { container } = render(stage)
      expect((container.textContent ?? '').length, `stage ${i} is empty`).toBeGreaterThan(120)
    }
  })

  it('animated classes never carry opacity-0 or visibility as a base style', () => {
    // A base style that hides content would leave a no-JS visitor with a blank
    // page. Entrance states live behind data-entered, applied by the observer.
    const source = landingSource()
    expect(source).not.toMatch(/className="[^"]*\bopacity-0\b/)
    expect(source).not.toMatch(/className="[^"]*\binvisible\b/)
  })

  it('the CSS keeps scroll-driven animation behind both guards', () => {
    const css = readFileSync(join(ROOT, 'app', 'globals.css'), 'utf8')
    const descent = css.slice(css.indexOf('THE DESCENT'))
    expect(descent).toContain('prefers-reduced-motion: no-preference')
    expect(descent).toContain('@supports (animation-timeline: view())')
    // and the scrubbed keyframes must sit inside that supports block
    const supportsAt = descent.indexOf('@supports (animation-timeline: view())')
    expect(descent.indexOf('.descent-acquire {')).toBeGreaterThan(supportsAt)
  })
})

describe('the figures are deterministic and captioned', () => {
  it.each([
    ['hero', <HeroFigure key="h" />],
    ['break', <BreakFigure key="k" />],
    ['b-scan', <BScanFigure key="b" />],
    ['frames', <FrameFigure key="f" />],
  ])('%s geometry is identical across renders', (_name, figure) => {
    const a = render(figure).container.innerHTML
    const b = render(figure).container.innerHTML
    expect(a).toEqual(b)
  })

  it.each([
    ['hero', <HeroFigure key="h" />],
    ['break', <BreakFigure key="k" />],
    ['b-scan', <BScanFigure key="b" />],
    ['frames', <FrameFigure key="f" />],
  ])('%s carries a screen-reader description saying it is an illustration', (_n, figure) => {
    render(figure)
    const img = screen.getAllByRole('img')[0]
    expect(img?.getAttribute('aria-label') ?? '').toMatch(/illustrat/i)
  })

  it('every stage drawing geometry says it is illustrative in the DOM', () => {
    for (const stage of [
      <StageBreak key="b" />,
      <StageSignal key="s" />,
      <StageCandidate key="c" />,
      <StageFrame key="f" />,
      <StageFusion key="u" />,
    ]) {
      const { container } = render(stage)
      expect(container.textContent ?? '').toMatch(/illustrative/i)
    }
  })

  it('no figure prints a numeric axis value', () => {
    for (const figure of [<HeroFigure key="h" />, <BreakFigure key="k" />, <BScanFigure key="b" />, <FrameFigure key="f" />]) {
      const { container } = render(figure)
      for (const text of Array.from(container.querySelectorAll('text'))) {
        expect(text.textContent ?? '').not.toMatch(/\d/)
      }
    }
  })
})

describe('the seams carry a motif across every boundary', () => {
  it('renders a bridge between stages without asserting anything', () => {
    const { container } = render(<Bridge from="trace" to="axes" label="x" />)
    // decorative by construction: hidden from assistive tech, no role
    expect(container.firstElementChild?.getAttribute('aria-hidden')).toBe('true')
    expect(container.querySelectorAll('path,rect,line').length).toBeGreaterThan(4)
  })

  it('is deterministic like every other figure', () => {
    const a = render(<Bridge from="frames" to="chips" />).container.innerHTML
    const b = render(<Bridge from="frames" to="chips" />).container.innerHTML
    expect(a).toEqual(b)
  })

  it('the page places a bridge at each seam it claims to join', () => {
    const page = readFileSync(join(ROOT, 'app', 'page.tsx'), 'utf8')
    // one seam per adjacent pair that is not already joined by the break event
    for (const pair of [
      'from="contour" to="trace"',
      'from="trace" to="axes"',
      'from="axes" to="frames"',
      'from="frames" to="chips"',
      'from="chips" to="bars"',
      'from="bars" to="panes"',
    ]) {
      expect(page).toContain(pair)
    }
  })
})

describe('the b-scan survives a narrow viewport', () => {
  it('offers a portrait composition, not a shrunken landscape', () => {
    const land = render(<BScanFigure />).container.querySelector('svg')
    const port = render(<BScanFigure portrait />).container.querySelector('svg')
    expect(land?.getAttribute('viewBox')).not.toEqual(port?.getAttribute('viewBox'))

    const [, , lw, lh] = (land?.getAttribute('viewBox') ?? '').split(' ').map(Number)
    const [, , pw, ph] = (port?.getAttribute('viewBox') ?? '').split(' ').map(Number)
    // landscape is wider than tall; portrait is taller than wide
    expect(lw! / lh!).toBeGreaterThan(1.5)
    expect(pw! / ph!).toBeLessThan(1.2)
  })

  it('enlarges its labels in portrait rather than scaling them down', () => {
    const size = (portrait: boolean) => {
      const { container } = render(<BScanFigure portrait={portrait} />)
      const t = container.querySelector('text') as SVGTextElement | null
      return parseFloat((t?.style.fontSize ?? '0').replace('px', ''))
    }
    expect(size(true)).toBeGreaterThan(size(false))
  })

  it('keeps the same targets, so the science is unchanged by the crop', () => {
    const land = render(<BScanFigure />).container.querySelectorAll('path').length
    const port = render(<BScanFigure portrait />).container.querySelectorAll('path').length
    expect(land).toBeGreaterThan(0)
    expect(port).toBeGreaterThan(0)
  })
})

describe('candidate is never promoted to detection', () => {
  it('marks exactly one arrival and leaves the others bare', () => {
    const { container } = render(<BScanFigure markers={[1]} />)
    const labels = Array.from(container.querySelectorAll('text')).map((t) => t.textContent)
    expect(labels.filter((l) => l === 'candidate')).toHaveLength(1)
  })

  it('separates signal, candidate, detection and validated result', () => {
    const { container } = render(<StageCandidate />)
    const text = (container.textContent ?? '').toLowerCase()
    for (const term of ['signal', 'candidate', 'detection', 'validated result']) {
      expect(text).toContain(term)
    }
    expect(text).toContain('chance')
    expect(text).toContain('rejected')
  })

  it('claims no detection accuracy anywhere on the page', () => {
    const source = landingSource()
    expect(source).not.toMatch(/\d+(\.\d+)?%\s*(accuracy|precision|recall|uptime|faster)/i)
    expect(source).not.toMatch(/\b\d+(\.\d+)?x\s+(faster|better|more accurate)\b/i)
    expect(source).not.toMatch(/\b\d+\s*\+\s*(customers|users|surveys|companies|teams)\b/i)
  })
})

describe('the blocked gates stay blocked', () => {
  it('renders both gates with BLOCKED intact', () => {
    const { container } = render(<StageGates />)
    const gates = container.querySelectorAll('[data-gate-status]')
    expect(gates).toHaveLength(2)
    for (const gate of Array.from(gates)) {
      expect(gate.getAttribute('data-gate-status')).toBe('BLOCKED')
    }
  })

  it('never claims localisation is validated, unlocked or available', () => {
    const source = landingSource().toLowerCase()
    for (const claim of [
      'localisation is validated',
      'localisation validated',
      'validated localisation',
      'localisation available',
      'localisation resolved',
      'localisation unlocked',
      'millimetre-accurate',
      'centimetre-accurate',
    ]) {
      expect(source).not.toContain(claim)
    }
  })

  it('invents no coordinate origin or vertical datum', () => {
    const source = landingSource().toLowerCase()
    expect(source).not.toMatch(/origin (is|has been) (verified|declared|established)/)
    expect(source).not.toMatch(/vertical datum (is|has been) (declared|established|resolved)/)
    // the honest statements must still be present
    expect(source).toContain('corroborated but not declared')
    expect(source).toContain('undeclared')
  })
})

describe('the page stands alone', () => {
  it('fetches nothing and imports no data hook or API client', () => {
    const source = landingSource()
    expect(source).not.toMatch(/from\s+['"]@\/services\/api['"]/)
    expect(source).not.toMatch(/from\s+['"]@\/hooks\/use-subterra['"]/)
    expect(source).not.toMatch(/\bfetch\s*\(/)
    expect(source).not.toMatch(/\buseSWR\b/)
  })

  it('introduces no 3D runtime and no randomness', () => {
    const source = landingSource()
    const randomCall = new RegExp(['Math', '\\.', 'random', '\\s*\\('].join(''))
    expect(source).not.toMatch(randomCall)
    expect(source).not.toMatch(/from\s+['"]three/)
    expect(source).not.toMatch(/@react-three/)

    const pkg = JSON.parse(readFileSync(join(ROOT, 'package.json'), 'utf8'))
    const deps = { ...pkg.dependencies, ...pkg.devDependencies }
    expect(
      Object.keys(deps).filter(
        (d) => d === 'three' || d.startsWith('@react-three/') || d === '@types/three',
      ),
    ).toEqual([])
  })

  it('uses no external image, video or stock asset', () => {
    const source = landingSource()
    expect(source).not.toMatch(/https?:\/\/(?!www\.w3\.org)/)
    expect(source).not.toMatch(/\.(png|jpg|jpeg|gif|webp|avif|mp4|webm)\b/i)
  })

  it('contains no fabricated social proof', () => {
    const source = landingSource().toLowerCase()
    for (const banned of [
      'testimonial', 'trusted by', 'our customers', 'case study',
      'backed by', 'as seen in', 'loved by', 'join thousands',
    ]) {
      expect(source).not.toContain(banned)
    }
    expect(source).not.toMatch(/\brated\b/)
  })
})

describe('existing routes stay reachable', () => {
  it.each([
    ['nav', <LandingNav key="n" />],
    ['surface', <StageSurface key="s" />],
    ['view', <StageView key="v" />],
  ])('%s links resolve to real routes', (_name, element) => {
    const { container } = render(element)
    const hrefs = Array.from(container.querySelectorAll('a[href]')).map((a) =>
      a.getAttribute('href'),
    )
    expect(hrefs.length).toBeGreaterThan(0)
    for (const href of hrefs) {
      if (href?.startsWith('#')) continue
      expect(REAL_ROUTES).toContain(href)
    }
  })

  it('offers a primary route into the workspace and one to the benchmarks', () => {
    render(<StageSurface />)
    const [enter] = screen.getAllByRole('link', { name: /enter the workspace/i })
    expect(enter?.getAttribute('href')).toBe('/datasets')
    const [evidence] = screen.getAllByRole('link', { name: /evidence and benchmarks/i })
    expect(evidence?.getAttribute('href')).toBe('/benchmark')
  })
})
