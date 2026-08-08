import { StateBox } from './state-box'

/**
 * A build-stage placeholder for a panel whose API adapter is not yet wired.
 *
 * This exists so the shell can be reviewed before any data flows, without
 * ever showing a plausible-looking number that isn't real. It is
 * deliberately blunt: it names the endpoint that will fill the panel, so a
 * reader can tell "not built yet" from "the backend has nothing" from "the
 * backend refused" -- three states that must never be confused.
 *
 * Every use of this component is a to-do. It is expected to disappear as
 * the API adapters land; a lint of "how much of this remains" is a fair
 * measure of integration progress.
 */
export function NotConnected({
  endpoint,
  what,
}: {
  /** The real endpoint that will supply this panel, e.g. `GET /api/datasets/`. */
  endpoint: string
  /** What the panel will show once connected. */
  what: string
}) {
  return (
    <StateBox
      kind="empty"
      title="Not connected yet"
      detail={`${what} will be read from ${endpoint}. The API adapter for this panel has not been wired up, so nothing is displayed here rather than placeholder data.`}
    />
  )
}
