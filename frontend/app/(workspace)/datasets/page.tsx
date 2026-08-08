import { AppHeader } from '@/components/shell/app-header'
import { Panel, PanelBody, PanelHeader } from '@/components/subterra/panel'
import { NotConnected } from '@/components/subterra/not-connected'

/**
 * Dataset index.
 *
 * Shell only: the list is not wired to `GET /api/datasets/` yet, so it
 * shows an explicit not-connected state rather than sample rows.
 */
export default function DatasetsPage() {
  return (
    <>
      <AppHeader
        title="Datasets"
        subtitle="Ingested surveys, their frames and their declared spatial references"
      />
      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        <div className="mx-auto max-w-5xl">
          <Panel>
            <PanelHeader title="Ingested datasets" />
            <PanelBody>
              <NotConnected
                endpoint="GET /api/datasets/"
                what="The dataset registry, filterable by sensor type, quality score and ground-truth availability,"
              />
            </PanelBody>
          </Panel>
        </div>
      </div>
    </>
  )
}
