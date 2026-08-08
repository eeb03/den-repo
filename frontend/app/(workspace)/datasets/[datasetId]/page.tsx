import { AppHeader } from '@/components/shell/app-header'
import {
  Panel,
  PanelBody,
  PanelHeader,
  SectionLabel,
} from '@/components/subterra/panel'
import { NotConnected } from '@/components/subterra/not-connected'

/**
 * The dataset workspace.
 *
 * Three panes, deliberately mirroring `visualization/thin_client.html`
 * rather than inventing a new information architecture:
 *
 *   left    dataset context -- layers, objects, labels, and the
 *           "Not on the map" list that keeps unplaced items reachable
 *   centre  the spatial views -- map over radargram
 *   right   the selection, and every view's resolution with the backend's
 *           reason for the ones that do not resolve
 *
 * The centre pane will host the existing proven Plotly visualisation
 * before any React port is attempted; the backend and the existing viewer
 * remain authoritative for all spatial mathematics.
 *
 * Shell only at this stage -- no adapter is wired, so each region states
 * which endpoint will fill it.
 */
export default async function DatasetWorkspacePage({
  params,
}: {
  params: Promise<{ datasetId: string }>
}) {
  const { datasetId } = await params

  return (
    <>
      <AppHeader title="Dataset workspace" subtitle={datasetId} />

      <div className="grid min-h-0 flex-1 grid-cols-[17rem_minmax(0,1fr)_20rem] gap-3 p-3">
        {/* ---------------------------- left ---------------------------- */}
        <Panel>
          <PanelHeader title="Dataset" />
          <PanelBody className="pt-0">
            <SectionLabel>Layers</SectionLabel>
            <NotConnected
              endpoint="GET /api/overlays/{id}/layers"
              what="Survey frames with their native CRS and the provenance of any WGS84 extent,"
            />

            <SectionLabel>Objects</SectionLabel>
            <NotConnected
              endpoint="GET /api/objects/{id}"
              what="Resolved subsurface objects, split into placed and unplaced,"
            />

            <SectionLabel>Labels</SectionLabel>
            <NotConnected
              endpoint="GET /api/labels/{id}"
              what="Semantic labels with their kind, source, provenance and confidence,"
            />

            <SectionLabel>Not on the map</SectionLabel>
            <NotConnected
              endpoint="GET /api/objects/{id} + /api/labels/{id}"
              what="Items that exist but carry no geographic position, each with its reason,"
            />
          </PanelBody>
        </Panel>

        {/* --------------------------- centre --------------------------- */}
        <div className="grid min-h-0 grid-rows-2 gap-3">
          <Panel>
            <PanelHeader title="Map" />
            <PanelBody className="subterra-grid flex items-center justify-center">
              <div className="w-full max-w-md">
                <NotConnected
                  endpoint="GET /api/objects/{id} + /api/labels/{id}"
                  what="Geographically positioned items only, with marker shape encoding position provenance,"
                />
              </div>
            </PanelBody>
          </Panel>

          <Panel>
            <PanelHeader title="Radargram" />
            <PanelBody className="subterra-grid flex items-center justify-center">
              <div className="w-full max-w-md">
                <NotConnected
                  endpoint="GET /api/datasets/{id}/trace_grid"
                  what="The trace grid for the selected line, with its vertical axis labelled as the backend reports it,"
                />
              </div>
            </PanelBody>
          </Panel>
        </div>

        {/* ---------------------------- right --------------------------- */}
        <Panel>
          <PanelHeader title="Selection" />
          <PanelBody className="pt-0">
            <SectionLabel>Selected</SectionLabel>
            <NotConnected
              endpoint="(client-side, from identifiers the API returned)"
              what="The view-independent selection identity,"
            />

            <SectionLabel>Views</SectionLabel>
            <NotConnected
              endpoint="POST /api/views/resolve"
              what="Each view either resolved, or unavailable with the backend's reason and missing list,"
            />

            <SectionLabel>Overlay composition</SectionLabel>
            <NotConnected
              endpoint="POST /api/overlays/compose"
              what="The spatial relationship, its basis, and the vertical relationship,"
            />
          </PanelBody>
        </Panel>
      </div>
    </>
  )
}
