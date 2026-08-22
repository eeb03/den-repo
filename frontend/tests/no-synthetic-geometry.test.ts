/**
 * No synthetic geometry reaches the scientific workspace.
 *
 * The v0 design shipped `UndergroundScene`, 361 lines of three.js that
 * generates its point cloud with `Math.random()`. It is decorative art. If
 * it were ever wired to a dataset it would render a fabricated subsurface
 * that looks exactly like a measured one -- the single most damaging thing
 * this UI could do, because unlike a wrong number it carries no units a
 * reader could sanity-check.
 *
 * The rule targets fabrication, not the rendering technology: no source
 * file may generate its own geometry (`Math.random()`, a literal null-island
 * coordinate, a depth/elevation derived client-side from a velocity -- see
 * the two describe blocks below). `components/scene/reconstructed-scene.tsx`
 * legitimately imports `three` to render the `/api/scene` payload -- real
 * positions and elevations traced to backend-declared/derived values, never
 * generated in the browser -- and carries its own honesty guard in
 * `reconstructed-scene.test.tsx` (unresolved datasets get no canvas at all;
 * `validation_status` is always shown verbatim; ungrounded candidates are
 * listed as "not shown", never drawn). `UndergroundScene`/`HeroScene`/
 * `SceneViewport`, the specific decorative v0 components, remain banned by
 * name below regardless of which package they'd be built on.
 *
 * Scope note: `visualization/viewer.html` legitimately renders 3D from real
 * `/points` data via Plotly and is out of scope here; its own honesty guard
 * lives in `tests/test_viewer_positions.py`.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { describe, expect, it } from 'vitest'

const ROOT = join(__dirname, '..')

/** Directories that make up the scientific workspace. */
const WORKSPACE_DIRS = ['app', 'components', 'hooks', 'lib', 'services', 'types']

function sourceFiles(): string[] {
  const out: string[] = []
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir)) {
      if (entry === 'node_modules' || entry.startsWith('.')) continue
      const full = join(dir, entry)
      if (statSync(full).isDirectory()) walk(full)
      else if (/\.(ts|tsx)$/.test(full) && !/\.test\.tsx?$/.test(full)) out.push(full)
    }
  }
  for (const dir of WORKSPACE_DIRS) walk(join(ROOT, dir))
  return out
}

const FILES = sourceFiles()

/** Import statements only -- so prose like "three-pane layout" is not a hit. */
function importsOf(source: string): string[] {
  return [
    ...source.matchAll(/(?:^|\n)\s*import\s[^\n]*?from\s+['"]([^'"]+)['"]/g),
    ...source.matchAll(/\bimport\(\s*['"]([^'"]+)['"]\s*\)/g),
    ...source.matchAll(/\brequire\(\s*['"]([^'"]+)['"]\s*\)/g),
  ].map((m) => m[1] as string)
}

describe('the workspace adds no heavier 3D framework than the one real scene needs', () => {
  it('scans a non-trivial number of files', () => {
    // guards against the walker silently finding nothing and passing
    expect(FILES.length).toBeGreaterThan(15)
  })

  // `three` itself (and its OrbitControls example module) is allowed: it
  // renders /api/scene's real, backend-derived positions. A React
  // reconciler on top of it (react-three-fiber/drei) is not -- if a second
  // scene is ever justified, that decision should be made deliberately, not
  // arrive as a transitive default.
  it.each(['@react-three/fiber', '@react-three/drei'])('no source file imports %s', (pkg) => {
    for (const file of FILES) {
      const imports = importsOf(readFileSync(file, 'utf8'))
      expect(
        imports.some((i) => i === pkg || i.startsWith(`${pkg}/`)),
        `${relative(ROOT, file)} imports ${pkg}`,
      ).toBe(false)
    }
  })

  it('only reconstructed-scene.tsx imports three', () => {
    for (const file of FILES) {
      const imports = importsOf(readFileSync(file, 'utf8'))
      const importsThree = imports.some((i) => i === 'three' || i.startsWith('three/'))
      if (importsThree) {
        expect(relative(ROOT, file)).toBe('components/scene/reconstructed-scene.tsx')
      }
    }
  })

  it('no source file imports the v0 decorative scenes', () => {
    for (const file of FILES) {
      const source = readFileSync(file, 'utf8')
      for (const scene of ['UndergroundScene', 'HeroScene', 'SceneViewport']) {
        expect(source.includes(scene), `${relative(ROOT, file)} references ${scene}`).toBe(
          false,
        )
      }
    }
  })

  it('react-three-fiber/drei are not installed at all', () => {
    const pkg = JSON.parse(readFileSync(join(ROOT, 'package.json'), 'utf8'))
    const deps = { ...pkg.dependencies, ...pkg.devDependencies }
    const heavier = Object.keys(deps).filter((d) => d.startsWith('@react-three/'))
    expect(heavier).toEqual([])
  })
})

describe('the workspace generates no geometry of its own', () => {
  it('no source file calls Math.random()', () => {
    /*
     * Not a style rule. Every coordinate, depth and confidence this UI
     * displays must be traceable to the backend; a random number in a
     * component is by definition not. If randomness is ever genuinely
     * needed (a jitter, an id), it belongs somewhere it cannot be mistaken
     * for data, and this test should be narrowed deliberately rather than
     * deleted.
     */
    const offenders: string[] = []
    for (const file of FILES) {
      if (/Math\.random\s*\(/.test(readFileSync(file, 'utf8'))) {
        offenders.push(relative(ROOT, file))
      }
    }
    expect(offenders).toEqual([])
  })

  it('no source file constructs coordinates from a literal zero triple', () => {
    const offenders: string[] = []
    for (const file of FILES) {
      const source = readFileSync(file, 'utf8')
      // { x: 0, y: 0, z: 0 } or lat: 0, lon: 0 -- the null-island shapes
      if (
        /\bx\s*:\s*0\s*,\s*y\s*:\s*0\s*,\s*z\s*:\s*0\b/.test(source) ||
        /\blat\s*:\s*0\s*,\s*lon\s*:\s*0\b/.test(source)
      ) {
        offenders.push(relative(ROOT, file))
      }
    }
    expect(offenders).toEqual([])
  })
})

describe('the workspace does not compute spatial or vertical quantities', () => {
  it('no source file derives a depth or elevation from a velocity', () => {
    /*
     * Mirrors tests/test_thin_client.py::
     * test_the_client_never_computes_elevation_or_depth. The UI may DISPLAY
     * a depth the backend derived; it may not derive one, because doing so
     * means assuming a propagation velocity -- the exact number the
     * vertical-reference investigation established the platform does not
     * have.
     */
    const banned = [
      /\bvelocity\s*\*/,
      /\*\s*velocity\b/,
      /\btoElevation\b/,
      /\bcomputeZ\b/,
      /\bdepthFrom\b/,
      /\belevationFrom\b/,
    ]
    const offenders: string[] = []
    for (const file of FILES) {
      // strip comments and string literals: the UI legitimately MENTIONS
      // velocity in the axis label it renders
      const code = readFileSync(file, 'utf8')
        .replace(/\/\*[\s\S]*?\*\//g, ' ')
        .replace(/\/\/[^\n]*/g, ' ')
        .replace(/'(?:[^'\\]|\\.)*'/g, "''")
        .replace(/"(?:[^"\\]|\\.)*"/g, '""')
        .replace(/`(?:[^`\\]|\\.)*`/g, '``')
      if (banned.some((re) => re.test(code))) offenders.push(relative(ROOT, file))
    }
    expect(offenders).toEqual([])
  })
})
