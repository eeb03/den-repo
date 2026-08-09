'use client'

import { useState } from 'react'
import Link from 'next/link'
import { SubterraLogo } from '@/components/brand/logo'
import { buttonVariants } from '@/components/ui/button'
import { ApiError, api } from '@/services/api'
import { cn } from '@/lib/utils'

/**
 * Request a password reset link.
 *
 * THE SUCCESS MESSAGE IS THE SAME EITHER WAY, and it has to be. The API
 * deliberately answers identically for a registered address and an unknown one,
 * so this page must not undo that by saying "check your inbox" for one and
 * "no account found" for the other. The wording therefore hedges on purpose:
 * "If an account exists for that address…".
 *
 * That is mildly worse UX for someone who mistypes their address, and it is the
 * right trade: the alternative hands anyone a way to test which addresses have
 * accounts here, one request at a time.
 */
export function ForgotPasswordForm() {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const [sentMessage, setSentMessage] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const { message } = await api.forgotPassword(email)
      // The backend's own generic wording is shown verbatim, not a friendlier
      // local copy that could drift into implying the account exists.
      setSentMessage(message)
      setSent(true)
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.detail
          : 'could not reach the Subterra API. Is the backend running?',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="flex min-h-svh items-center justify-center px-5 py-16">
      <div className="w-full max-w-sm">
        <Link href="/" className="inline-flex" aria-label="Subterra home">
          <SubterraLogo />
        </Link>

        <h1 className="mt-9 text-2xl font-semibold tracking-tight text-foreground">
          Reset your password
        </h1>

        {sent ? (
          <div data-forgot-sent>
            <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
              {sentMessage}
            </p>
            <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
              The link expires in 30 minutes and can be used once. If nothing
              arrives, check the address and try again.
            </p>
            <Link
              href="/login"
              className={cn(buttonVariants({ variant: 'outline', size: 'lg' }), 'mt-7 w-full')}
            >
              Back to sign in
            </Link>
          </div>
        ) : (
          <>
            <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
              Enter your email and we will send a link to choose a new one.
            </p>

            <form onSubmit={submit} className="mt-8 space-y-4" noValidate>
              <div>
                <label
                  htmlFor="email"
                  className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground"
                >
                  Email
                </label>
                <input
                  id="email"
                  name="email"
                  type="email"
                  value={email}
                  required
                  autoComplete="email"
                  onChange={(e) => setEmail(e.target.value)}
                  className="mt-1.5 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                />
              </div>

              {error && (
                <p
                  data-auth-error
                  role="alert"
                  className="subterra-hatch rounded-lg border border-destructive/40 px-3 py-2 text-xs leading-relaxed text-foreground"
                >
                  {error}
                </p>
              )}

              <button
                type="submit"
                disabled={busy}
                className={cn(buttonVariants({ variant: 'default', size: 'lg' }), 'w-full')}
              >
                {busy ? 'Sending…' : 'Send reset link'}
              </button>
            </form>

            <p className="mt-6 text-xs text-muted-foreground">
              Remembered it?{' '}
              <Link href="/login" className="text-primary underline-offset-4 hover:underline">
                Sign in
              </Link>
            </p>
          </>
        )}
      </div>
    </main>
  )
}
