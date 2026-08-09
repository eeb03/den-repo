'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { useSWRConfig } from 'swr'
import { SubterraLogo } from '@/components/brand/logo'
import { buttonVariants } from '@/components/ui/button'
import { ApiError, api } from '@/services/api'
import { cn } from '@/lib/utils'

/**
 * Sign in / create account.
 *
 * ONE COMPONENT FOR BOTH because the two forms differ by a single field and a
 * verb; two near-identical files would drift, and the error handling is the
 * part worth getting right once.
 *
 * ERRORS ARE THE BACKEND'S OWN, and deliberately so. A wrong password says
 * "invalid email or password" -- the API refuses to distinguish a missing
 * account from a wrong password, so the interface cannot either, and neither
 * can an attacker enumerating addresses. A duplicate registration DOES say so,
 * because the account could not be created either way and hiding it would leave
 * the user with no action to take.
 *
 * No stack trace ever reaches the screen: `ApiError.detail` is the backend's
 * message, and anything else renders as a plain connection failure.
 */
export function AuthForm({ mode }: { mode: 'login' | 'register' }) {
  const router = useRouter()
  const params = useSearchParams()
  const { mutate } = useSWRConfig()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const registering = mode === 'register'
  // Only ever an internal path: an open redirect would let a link sign someone
  // in and bounce them to another origin.
  const raw = params.get('next') ?? '/datasets'
  const next = raw.startsWith('/') && !raw.startsWith('//') ? raw : '/datasets'

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (registering) {
        await api.register(email, password, displayName || undefined)
      } else {
        await api.login(email, password)
      }
      await mutate('current-user')
      router.replace(next)
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
          {registering ? 'Create an account' : 'Sign in'}
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          {registering
            ? 'An account owns the datasets you import. Nothing else is collected.'
            : 'Datasets you import are visible only to you.'}
        </p>

        <form onSubmit={submit} className="mt-8 space-y-4" noValidate>
          <Field
            id="email"
            label="Email"
            type="email"
            value={email}
            onChange={setEmail}
            autoComplete="email"
            required
          />
          {registering && (
            <Field
              id="display_name"
              label="Display name"
              hint="optional"
              value={displayName}
              onChange={setDisplayName}
              autoComplete="name"
            />
          )}
          <Field
            id="password"
            label="Password"
            type="password"
            value={password}
            onChange={setPassword}
            hint={registering ? 'at least 10 characters' : undefined}
            autoComplete={registering ? 'new-password' : 'current-password'}
            required
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
            {busy
              ? registering
                ? 'Creating account…'
                : 'Signing in…'
              : registering
                ? 'Create account'
                : 'Sign in'}
          </button>
        </form>

        {!registering && (
          <p className="mt-4 text-xs text-muted-foreground">
            <Link
              href="/forgot-password"
              className="text-primary underline-offset-4 hover:underline"
            >
              Forgot password?
            </Link>
          </p>
        )}

        <p className="mt-6 text-xs text-muted-foreground">
          {registering ? 'Already have an account? ' : 'No account yet? '}
          <Link
            href={registering ? '/login' : '/register'}
            className="text-primary underline-offset-4 hover:underline"
          >
            {registering ? 'Sign in' : 'Create one'}
          </Link>
        </p>
      </div>
    </main>
  )
}

function Field({
  id,
  label,
  value,
  onChange,
  type = 'text',
  hint,
  required,
  autoComplete,
}: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  type?: string
  hint?: string
  required?: boolean
  autoComplete?: string
}) {
  return (
    <div>
      <label
        htmlFor={id}
        className="flex items-baseline justify-between font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground"
      >
        {label}
        {hint && <span className="tracking-normal normal-case">{hint}</span>}
      </label>
      <input
        id={id}
        name={id}
        type={type}
        value={value}
        required={required}
        autoComplete={autoComplete}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1.5 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
      />
    </div>
  )
}
