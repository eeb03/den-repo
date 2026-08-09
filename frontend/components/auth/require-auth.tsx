'use client'

import { useEffect } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import { useCurrentUser } from '@/hooks/use-subterra'
import { Skeleton } from '@/components/ui/skeleton'

/**
 * Gate for the workspace shell.
 *
 * THIS IS CONVENIENCE, NOT SECURITY, and the distinction matters enough to
 * state: hiding a route in the browser protects nothing. Every dataset,
 * import job, record, frame, overlay and provenance endpoint is authorised
 * server-side in auth/dependencies.py, and would refuse an unauthenticated
 * caller with this component deleted. What this does is stop a signed-out
 * visitor being shown a workspace full of 401s.
 *
 * While the answer is unknown the children are NOT rendered. Rendering them
 * optimistically would fire a burst of requests that all fail, and would flash
 * an empty workspace before the redirect.
 */
/**
 * Routes inside the workspace shell that stay readable signed out.
 *
 * The benchmark page renders the frozen artifacts, which `/api/benchmark/*`
 * serves publicly on purpose: THE DESCENT invites a reader to go and check our
 * results, and a login wall in front of published evidence would make that
 * invitation false. Nothing user-owned is reachable from it.
 */
const PUBLIC_PATHS = ['/benchmark']

export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { data: user, isLoading, error } = useCurrentUser()
  const router = useRouter()
  const pathname = usePathname()
  const isPublic = PUBLIC_PATHS.some(
    (p) => pathname === p || pathname?.startsWith(`${p}/`),
  )

  useEffect(() => {
    if (!isPublic && !isLoading && !error && user === null) {
      // Carry the destination so signing in returns the visitor where they were.
      router.replace(`/login?next=${encodeURIComponent(pathname || '/datasets')}`)
    }
  }, [user, isLoading, error, router, pathname, isPublic])

  if (isPublic) return <>{children}</>

  if (isLoading || user === null) {
    return (
      <div className="flex min-h-svh flex-col gap-3 p-6" aria-busy="true">
        <Skeleton className="h-8 w-52" />
        <Skeleton className="h-4 w-80" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  if (error) {
    // A network failure is NOT "signed out": redirecting would hide a backend
    // outage behind a login screen and send the user in circles.
    return (
      <div className="flex min-h-svh items-center justify-center p-6">
        <div className="max-w-md">
          <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-destructive">
            Cannot reach the platform
          </p>
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
            The workspace could not ask the API who you are. This is a
            connection problem, not a sign-in problem — the session, if you have
            one, is intact.
          </p>
        </div>
      </div>
    )
  }

  return <>{children}</>
}
