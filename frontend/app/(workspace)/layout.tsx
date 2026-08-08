import { AppSidebar } from '@/components/shell/app-sidebar'

/**
 * The workspace shell: a fixed sidebar beside a scroll-contained main area.
 *
 * `h-svh` + `min-h-0` throughout is what lets the three-pane dataset
 * workspace own its own scrolling regions instead of the page scrolling as
 * a whole -- necessary for a dense analysis surface where the map and
 * radargram must stay visible while lists scroll independently.
 */
export default function WorkspaceLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <div className="flex h-svh overflow-hidden">
      <AppSidebar />
      <div className="flex min-w-0 flex-1 flex-col">{children}</div>
    </div>
  )
}
