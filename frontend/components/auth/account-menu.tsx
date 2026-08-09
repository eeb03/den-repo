'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { LogOut } from 'lucide-react'
import { useSWRConfig } from 'swr'
import { useCurrentUser } from '@/hooks/use-subterra'
import { api } from '@/services/api'
import { cn } from '@/lib/utils'

/**
 * Who is signed in, and the way out.
 *
 * Logout calls the API before clearing anything locally, because the session
 * is server-side: dropping the cookie alone would leave a token that still
 * authenticates if it had been captured. The local cache is only cleared once
 * the server has revoked the row.
 */
export function AccountMenu({ className }: { className?: string }) {
  const { data: user } = useCurrentUser()
  const { mutate } = useSWRConfig()
  const router = useRouter()
  const [busy, setBusy] = useState(false)

  if (!user) return null

  async function signOut() {
    setBusy(true)
    try {
      await api.logout()
    } finally {
      // Whatever the server said, this browser is done with the session.
      await mutate(() => true, undefined, { revalidate: false })
      router.replace('/login')
    }
  }

  const label = user.display_name || user.email

  return (
    <div className={cn('border-t border-sidebar-border px-3 py-3', className)}>
      <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
        Signed in
      </p>
      <p
        data-account-label
        className="mt-1 truncate text-xs text-foreground"
        title={user.email}
      >
        {label}
      </p>
      <button
        type="button"
        onClick={signOut}
        disabled={busy}
        className="mt-2.5 inline-flex items-center gap-1.5 rounded-md text-[11px] text-muted-foreground outline-none transition-colors hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50"
      >
        <LogOut className="size-3" aria-hidden />
        {busy ? 'Signing out…' : 'Sign out'}
      </button>
    </div>
  )
}
