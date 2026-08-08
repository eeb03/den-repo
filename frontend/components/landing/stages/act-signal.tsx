import { IllustrativeNote, Stage, StageMark } from '../descent'
import { BScanFigure } from '../figures/bscan-figure'

/**
 * Stage 2 — SIGNAL, and Stage 3 — CANDIDATE ≠ DETECTION.
 *
 * Stage 3 is the page's honesty moment and the reason the figure in stage 2
 * has three targets rather than one: here exactly ONE apex is ringed as a
 * candidate, and the other two are left bare. That asymmetry is the argument.
 * An unmarked arrival has not been declared absent, and a marked one has not
 * been declared a pipe.
 */

export function StageSignal() {
  return (
    <Stage id="signal" index={2}>
      <div className="max-w-2xl">
        <StageMark index={2}>Signal</StageMark>
        <h2
          id="signal-heading"
          className="text-balance text-3xl font-semibold tracking-tight text-foreground sm:text-4xl"
        >
          A radargram is a signal, not a photograph
        </h2>
        <p className="mt-5 text-pretty text-sm leading-relaxed text-muted-foreground sm:text-base">
          Push an antenna along a line and each position returns one trace. A
          buried point does not image as a point: the path lengthens as the
          antenna moves away, so it arrives late on either side and draws a
          hyperbola. Reading the ground means reading that shape.
        </p>
      </div>

      {/*
       * Full-bleed, and no border. A bordered box would read as a dashboard
       * card; the acquisition is the stage, so it is allowed to run to the
       * edges of the page. The instrument caption stays because it names what
       * the plot IS, which a reader needs.
       */}
      <figure className="descent-bleed mt-10">
        <div className="mx-auto flex max-w-6xl items-baseline justify-between gap-4 px-5 sm:px-8">
          <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
            B-scan · wiggle plot
          </span>
          <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-primary">
            acquiring
          </span>
        </div>
        <div className="mt-3 border-y border-border/60 bg-background/30">
          <BScanFigure scrubbed portrait className="h-[62svh] sm:hidden" />
          <BScanFigure scrubbed className="hidden max-h-[56svh] sm:block" />
        </div>
        <div className="mx-auto max-w-6xl px-5 sm:px-8">
          <IllustrativeNote>
            Illustrative geometry — generated from the hyperbola equation, not
            recorded from a survey
          </IllustrativeNote>
        </div>
      </figure>
    </Stage>
  )
}

export function StageCandidate() {
  return (
    <Stage id="candidate" index={3}>
      <div className="grid gap-12 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)] lg:gap-14">
        <figure>
          <div className="border-y border-border/60 bg-background/30">
            <BScanFigure markers={[1]} showHyperbolae={false} portrait className="h-[52svh] sm:hidden" />
            <BScanFigure markers={[1]} showHyperbolae={false} className="hidden max-h-[46svh] sm:block" />
          </div>
          <IllustrativeNote>
            Illustrative geometry — one arrival is marked; the others are not
            marked, and are not thereby declared absent
          </IllustrativeNote>
        </figure>

        <div>
          <StageMark index={3}>Candidate ≠ detection</StageMark>
          <h2
            id="candidate-heading"
            className="text-balance text-3xl font-semibold tracking-tight text-foreground sm:text-4xl"
          >
            The platform will not call this a pipe
          </h2>
          <p className="mt-5 text-pretty text-sm leading-relaxed text-muted-foreground sm:text-base">
            An anomaly detector responds to contrast. That response is a{' '}
            <span className="text-foreground">candidate</span> — a place worth
            looking. It is not a detection, it is not an identification, and it
            is not a validated result. Subterra keeps those four words apart
            because collapsing them is how a survey tool starts lying.
          </p>

          <ol className="mt-8 space-y-3">
            {[
              {
                term: 'Signal',
                body: 'Energy returned at some position and time. Measured.',
                tone: 'text-prov-measured',
              },
              {
                term: 'Candidate',
                body: 'A response that crossed a stated threshold. Derived, and reported as a count — never as a find.',
                tone: 'text-prov-derived',
              },
              {
                term: 'Detection',
                body: 'A candidate matched to a target under a published rule. Requires ground truth to score against.',
                tone: 'text-prov-inferred',
              },
              {
                term: 'Validated result',
                body: 'A detection whose evidence gate is open. For localisation, that gate is currently closed.',
                tone: 'text-prov-unavailable',
              },
            ].map((row, i) => (
              <li key={row.term} className="flex gap-4">
                <span className="tabular pt-0.5 font-mono text-[11px] text-muted-foreground/60">
                  {String(i + 1).padStart(2, '0')}
                </span>
                <div className="border-l border-border pl-4">
                  <p
                    className={`font-mono text-[11px] uppercase tracking-[0.18em] ${row.tone}`}
                  >
                    {row.term}
                  </p>
                  <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                    {row.body}
                  </p>
                </div>
              </li>
            ))}
          </ol>

          <p className="mt-8 border-l-2 border-warning/50 bg-warning/5 py-2.5 pl-4 pr-3 text-xs leading-relaxed text-muted-foreground">
            <span className="font-medium text-warning">Where we actually are. </span>
            The current detector sits at or near chance on both benchmarks. One
            candidate estimator was designed against the measured failure mode,
            pre-registered, evaluated and rejected; it is not in the default
            detection path. The benchmark page shows all of it at full precision.
          </p>
        </div>
      </div>
    </Stage>
  )
}
