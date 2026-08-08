/**
 * Deterministic geometry for the landing figures.
 *
 * Every function here is pure and closed-form: the same argument always
 * produces the same curve, on every render and every machine. Nothing is
 * sampled from a generator, nothing is fetched, and nothing carries units.
 *
 * That is a hard requirement rather than a preference.
 * `tests/no-synthetic-geometry.test.ts` scans this directory for any call into
 * the standard random generator and fails the suite on a match, because the v0
 * design shipped a subsurface scene whose point cloud was generated that way.
 * A randomly generated subsurface looks exactly like a measured one, which is
 * the single most damaging thing this interface could show.
 *
 * These curves ILLUSTRATE the physics of a radar section -- a surface
 * reflection, and the hyperbolic signature a buried point target leaves as an
 * antenna passes over it. They are not a survey, and every figure that uses
 * them says so in the DOM.
 */

/** Fixed sampling budget, so a figure cannot quietly grow expensive. */
export const MAX_SAMPLES = 200

function samples(n: number): number[] {
  const count = Math.min(n, MAX_SAMPLES)
  return Array.from({ length: count + 1 }, (_, i) => i / count)
}

export function path(points: Array<readonly [number, number]>): string {
  return `M ${points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' L ')}`
}

/**
 * Terrain relief: three harmonics with fixed phases. Not a landscape anyone
 * surveyed -- a legible line that behaves like ground does.
 */
export function terrain(
  width: number,
  base: number,
  amplitude: number,
  phase: number,
  n = 90,
): string {
  return path(
    samples(n).map((t) => {
      const x = t * width
      return [
        x,
        base +
          amplitude * Math.sin(x / 137 + phase) +
          amplitude * 0.42 * Math.sin(x / 52 + phase * 1.7) +
          amplitude * 0.19 * Math.sin(x / 21 + phase * 2.9),
      ] as const
    }),
  )
}

/**
 * The two-way travel path to a point target, in figure units.
 *
 * As the antenna moves away from a target the path lengthens, so a point
 * images as a downward-opening hyperbola rather than a point. `spread`
 * controls how quickly it opens. No propagation speed is named or implied --
 * the axis is unlabelled precisely because the platform has no established
 * vertical reference to label it with.
 */
export function arrivalAt(
  x: number,
  apexX: number,
  apexY: number,
  spread: number,
  depth: number,
): number {
  return apexY + depth * (Math.sqrt(1 + ((x - apexX) / spread) ** 2) - 1)
}

export function hyperbola(
  apexX: number,
  apexY: number,
  spread: number,
  depth: number,
  halfWidth: number,
  n = 60,
): string {
  return path(
    samples(n).map((t) => {
      const x = apexX + (t * 2 - 1) * halfWidth
      return [x, arrivalAt(x, apexX, apexY, spread, depth)] as const
    }),
  )
}

/**
 * A Ricker-like wavelet: what a reflection looks like on a single trace.
 *
 * A real arrival is a short oscillation with a dominant centre lobe, not a
 * spike -- which is why a radargram reads as banded rather than dotted. The
 * width is generous relative to the section height so the lobes are legible
 * at figure scale instead of collapsing into the trace line.
 */
function wavelet(distance: number, width: number): number {
  const u = distance / width
  if (Math.abs(u) > 3) return 0
  return (1 - 2 * (Math.PI * u) ** 2 * 0.22) * Math.exp(-((Math.PI * u) ** 2) * 0.22)
}

export interface Target {
  apexX: number
  apexY: number
  spread: number
  depth: number
}

/**
 * One wiggle trace of a B-scan: a vertical line deflected horizontally wherever
 * energy arrives -- the surface pulse near the top, plus one arrival per target
 * at the time its hyperbola predicts for this trace position.
 */
export function trace(
  x: number,
  top: number,
  bottom: number,
  targets: readonly Target[],
  gain: number,
  n = 56,
): string {
  return path(
    samples(n).map((t) => {
      const y = top + t * (bottom - top)
      // the surface reflection, present on every trace
      let deflection = wavelet(y - top - 10, 13) * 1.2
      for (const target of targets) {
        const arrival = arrivalAt(x, target.apexX, target.apexY, target.spread, target.depth)
        // energy falls off as the antenna moves off the target
        const falloff = 1 / (1 + ((x - target.apexX) / (target.spread * 1.15)) ** 2)
        deflection += wavelet(y - arrival, 11) * falloff
      }
      return [x + deflection * gain, y] as const
    }),
  )
}

/**
 * The same trace closed back along its baseline, so it can be filled.
 *
 * Filled wiggle traces are how a radargram is conventionally plotted: the
 * lobes merge across neighbouring traces into continuous bands, which is what
 * makes a reflector legible as a surface rather than as a row of squiggles.
 */
export function traceFilled(
  x: number,
  top: number,
  bottom: number,
  targets: readonly Target[],
  gain: number,
  n = 56,
): string {
  return `${trace(x, top, bottom, targets, gain, n)} L ${x.toFixed(1)},${bottom.toFixed(1)} L ${x.toFixed(1)},${top.toFixed(1)} Z`
}

/** Evenly spaced trace positions across the section. */
export function traceColumns(width: number, count: number, inset: number): number[] {
  const span = width - inset * 2
  return Array.from({ length: count }, (_, i) => inset + (span * i) / (count - 1))
}
