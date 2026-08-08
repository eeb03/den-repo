import { cn } from '@/lib/utils'
import { StateBox } from './state-box'
import { positionUnavailableReason, type Position } from '@/types/subterra'

/**
 * The "Not on the map" list.
 *
 * Ported from the thin client, where the rule is stated as:
 *
 *   "Nothing without a geographic position is plotted. Unplaced objects and
 *    labels are listed separately with their reason and stay reachable
 *    through the API. There is no fallback coordinate anywhere in the page,
 *    and a test greps for one."
 *
 * The list is the mechanism that makes that rule survivable. Without it,
 * refusing to plot an unpositioned object would look like losing it, and
 * the pressure to invent a coordinate would come straight back.
 *
 * Every entry states WHY it cannot be placed, using the backend's reason
 * where it gave one.
 */
export interface UnplacedItem {
  id: string
  /** 'object' | 'label' | anything else the caller lists. */
  itemType: string
  position: Position
}

export function NotOnMap({
  items,
  className,
  emptyTitle = 'Nothing unplaced',
  emptyDetail = 'Every object and label in this dataset has a geographic position.',
}: {
  items: UnplacedItem[]
  className?: string
  emptyTitle?: string
  emptyDetail?: string
}) {
  if (items.length === 0) {
    return (
      <StateBox
        kind="empty"
        title={emptyTitle}
        detail={emptyDetail}
        className={className}
      />
    )
  }

  return (
    <div className={cn('space-y-1.5', className)}>
      <p className="text-xs leading-relaxed text-muted-foreground">
        {items.length} item{items.length === 1 ? '' : 's'} exist and remain available
        through the API, but have no geographic position and are therefore not
        drawn.
      </p>
      <ul className="space-y-1.5">
        {items.map((item) => (
          <li
            key={`${item.itemType}:${item.id}`}
            data-unplaced={item.itemType}
            className="subterra-hatch rounded-lg border border-dashed border-prov-unavailable/40 px-2.5 py-2"
          >
            <div className="flex items-baseline gap-2">
              <span className="rounded border border-prov-unavailable/40 px-1 py-px text-[10px] uppercase tracking-wider text-prov-unavailable">
                {item.itemType}
              </span>
              <code className="truncate font-mono text-xs text-foreground">
                {item.id}
              </code>
            </div>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
              {positionUnavailableReason(item.position) ??
                'no geographic position; the backend supplied no reason'}
            </p>
          </li>
        ))}
      </ul>
    </div>
  )
}
