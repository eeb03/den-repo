'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { SubterraLogo } from '@/components/brand/logo'
import { buttonVariants } from '@/components/ui/button'
import { ApiError, api } from '@/services/api'
import { cn } from '@/lib/utils'

/**
 * Choose a new password, using the token from the emailed link.
 *
 * ONE MESSAGE FOR EVERY BAD TOKEN. Missing, malformed, expired, already used --
 * all render the same sentence, because the differences are only useful to
 * somebody guessing at tokens. A page that said "this link has expired" would
 * confirm the token had once been real.
 *
 * VALIDATION ERRORS ARE DIFFERENT, and are shown plainly: a password that is
 * too short or a confirmation that does not match is the user's own input, tells
 * an attacker nothing, and is something they can act on. The API is careful to
 * reject those BEFORE consuming the token, so a mistyped password does not burn
 * the link.
 */
const INVALID_LINK =
  'This password reset link is invalid or has expired. Please request a new one.'

export function ResetPasswordForm() {
  const params = useSearchParams()
  const token = params.get('token') ?? ''

  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState(false)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.resetPassword(token, password, confirmation)
      setDone(true)
    } catch (err) {
      if (err instanceof ApiError) {
        // 400 is the backend's single "bad token" answer; 422 is a validation
        // problem with what the user typed, which is safe to show verbatim.
        setError(err.status === 400 ? INVALID_LINK : err.detail)
      } else {
        setError('could not reach the Subterra API. Is the backend running?')
      }
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
          Choose a new password
        </h1>

        {/* A missing token is treated exactly like a bad one: same sentence. */}
        {!token ? (
          <div data-reset-invalid>
            <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
              {INVALID_LINK}
            </p>
            <Link
              href="/forgot-password"
              className={cn(buttonVariants({ variant: 'default', size: 'lg' }), 'mt-7 w-full')}
            >
              Request a new link
            </Link>
          </div>
        ) : done ? (
          <div data-reset-done>
            <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
              Your password has been changed. Any other browsers signed in to this
              account have been signed out.
            </p>
            <Link
              href="/login"
              className={cn(buttonVariants({ variant: 'default', size: 'lg' }), 'mt-7 w-full')}
            >
              Sign in
            </Link>
          </div>
        ) : (
          <>
            <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
              At least 10 characters. Signing in elsewhere will end those sessions.
            </p>

            <form onSubmit={submit} className="mt-8 space-y-4" noValidate>
              <Field
                id="password"
                label="New password"
                value={password}
                onChange={setPassword}
              />
              <Field
                id="password_confirmation"
                label="Confirm password"
                value={confirmation}
                onChange={setConfirmation}
              />

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
                {busy ? 'Changing…' : 'Change password'}
              </button>
            </form>

            <p className="mt-6 text-xs text-muted-foreground">
              <Link href="/login" className="text-primary underline-offset-4 hover:underline">
                Back to sign in
              </Link>
            </p>
          </>
        )}
      </div>
    </main>
  )
}

function Field({
  id,
  label,
  value,
  onChange,
}: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
}) {
  return (
    <div>
      <label
        htmlFor={id}
        className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground"
      >
        {label}
      </label>
      <input
        id={id}
        name={id}
        type="password"
        value={value}
        required
        autoComplete="new-password"
        onChange={(e) => onChange(e.target.value)}
        className="mt-1.5 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
      />
    </div>
  )
}
