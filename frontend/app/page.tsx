import { redirect } from 'next/navigation'

/**
 * The marketing landing page from the v0 design lands here in a later
 * phase, once its claims have been checked against what the platform
 * actually does. Until then the root sends operators to the workspace.
 */
export default function RootPage() {
  redirect('/datasets')
}
