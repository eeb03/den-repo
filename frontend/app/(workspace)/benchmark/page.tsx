import { AppHeader } from '@/components/shell/app-header'
import { Panel, PanelBody, PanelHeader } from '@/components/subterra/panel'
import { NotConnected } from '@/components/subterra/not-connected'
import { StateBox } from '@/components/subterra/state-box'

/**
 * Benchmark workspace.
 *
 * Shell only. The validated BAM and 4TU results live in
 * `artifacts/{bam,4tu}/*.json` and are NOT currently served by any
 * endpoint -- `/api/benchmark/` exposes only the generic `POST /score` and
 * `GET /runs` over the BenchmarkRun table. That gap is stated on the page
 * itself rather than filled with anything.
 *
 * Nothing here recomputes, rescales or reinterprets a benchmark figure.
 * When the results are connected they will be rendered exactly as the
 * artifacts report them, including the BLOCKED gates and the open
 * questions.
 */
export default function BenchmarkPage() {
  return (
    <>
      <AppHeader
        title="Benchmark"
        subtitle="Evaluation results, shown exactly as the platform reports them"
      />
      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        <div className="mx-auto max-w-5xl space-y-3">
          <StateBox
            kind="unavailable"
            title="Benchmark results are not reachable over the API"
            detail={
              'The validated BAM and 4TU results are written to artifacts/bam/*.json and ' +
              'artifacts/4tu/*.json by the scoring scripts. No endpoint currently serves them: ' +
              '/api/benchmark exposes only POST /score and GET /runs, which cover ad-hoc ' +
              'scoring runs rather than these committed evaluations. This page will stay ' +
              'empty until that is resolved, rather than restating figures from documentation.'
            }
            missing={[
              'a read-only endpoint exposing the benchmark artifacts',
            ]}
          />

          <Panel>
            <PanelHeader title="BAM — concrete GPR specimen" />
            <PanelBody>
              <NotConnected
                endpoint="artifacts/bam/*.json (no endpoint yet)"
                what="Detection metrics, the localisation gate status, provenance and the four open questions,"
              />
            </PanelBody>
          </Panel>

          <Panel>
            <PanelHeader title="4TU — real-world utility surveys" />
            <PanelBody>
              <NotConnected
                endpoint="artifacts/4tu/benchmark.json (no endpoint yet)"
                what="Activity-level results, the object-level gate status, and the three open questions,"
              />
            </PanelBody>
          </Panel>

          <Panel>
            <PanelHeader title="Ad-hoc scoring runs" />
            <PanelBody>
              <NotConnected
                endpoint="GET /api/benchmark/runs"
                what="Runs recorded by POST /api/benchmark/score,"
              />
            </PanelBody>
          </Panel>
        </div>
      </div>
    </>
  )
}
