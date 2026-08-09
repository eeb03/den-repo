/**
 * The password-reset screens.
 *
 * The property worth defending here is the same one the API defends: nothing on
 * these pages may tell a visitor whether an address has an account, and nothing
 * may distinguish an expired token from an invented one. A friendly "we could
 * not find that account" would undo the backend's care in a single line of JSX.
 */
import { render, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import { ApiError } from '@/services/api'

let searchParams = new URLSearchParams('')
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => '/forgot-password',
  useSearchParams: () => searchParams,
}))

const forgotPassword = vi.fn()
const resetPassword = vi.fn()
vi.mock('@/services/api', async () => {
  const actual = await vi.importActual<typeof import('@/services/api')>('@/services/api')
  return {
    ...actual,
    api: {
      ...actual.api,
      forgotPassword: (...a: unknown[]) => forgotPassword(...a),
      resetPassword: (...a: unknown[]) => resetPassword(...a),
    },
  }
})

import { ForgotPasswordForm } from './forgot-password-form'
import { ResetPasswordForm } from './reset-password-form'
import { AuthForm } from './auth-form'

const GENERIC =
  'If an account exists for that address, a password reset link has been sent.'
const INVALID =
  'This password reset link is invalid or has expired. Please request a new one.'

beforeEach(() => {
  forgotPassword.mockReset()
  resetPassword.mockReset()
  searchParams = new URLSearchParams('')
})

function submit(container: HTMLElement) {
  container.querySelector('form')!.dispatchEvent(
    new Event('submit', { bubbles: true, cancelable: true }),
  )
}

describe('the login page offers a way in', () => {
  it('links to forgot-password', () => {
    const { container } = render(<AuthForm mode="login" />)
    const link = Array.from(container.querySelectorAll('a')).find((a) =>
      /forgot password/i.test(a.textContent ?? ''),
    )
    expect(link?.getAttribute('href')).toBe('/forgot-password')
  })

  it('does not offer it on the registration form', () => {
    const { container } = render(<AuthForm mode="register" />)
    expect(container.textContent).not.toMatch(/forgot password/i)
  })
})

describe('forgot password', () => {
  it('renders an email field and a submit', () => {
    const { container } = render(<ForgotPasswordForm />)
    expect(container.querySelector('#email')).toBeTruthy()
    expect(container.querySelector('button[type=submit]')).toBeTruthy()
  })

  it('shows the generic acknowledgement on success', async () => {
    forgotPassword.mockResolvedValue({ message: GENERIC })
    const { container } = render(<ForgotPasswordForm />)
    submit(container)

    await waitFor(() => expect(container.querySelector('[data-forgot-sent]')).toBeTruthy())
    expect(container.textContent).toContain(GENERIC)
  })

  it('never says whether the account exists', async () => {
    forgotPassword.mockResolvedValue({ message: GENERIC })
    const { container } = render(<ForgotPasswordForm />)
    submit(container)
    await waitFor(() => expect(container.querySelector('[data-forgot-sent]')).toBeTruthy())

    const text = (container.textContent ?? '').toLowerCase()
    for (const leak of [
      'no account', 'not found', 'does not exist', 'unknown email',
      'check your inbox', 'we sent you', 'email sent to',
    ]) {
      expect(text).not.toContain(leak)
    }
  })

  it('handles a 429 without leaking why', async () => {
    forgotPassword.mockRejectedValue(new ApiError(429, 'too many requests'))
    const { container } = render(<ForgotPasswordForm />)
    submit(container)
    await waitFor(() => expect(container.querySelector('[data-auth-error]')).toBeTruthy())
    const text = (container.textContent ?? '').toLowerCase()
    expect(text).not.toContain('account')
  })

  it('reports a server failure as a failure, not as success', async () => {
    forgotPassword.mockRejectedValue(new ApiError(500, 'internal error'))
    const { container } = render(<ForgotPasswordForm />)
    submit(container)
    await waitFor(() => expect(container.querySelector('[data-auth-error]')).toBeTruthy())
    expect(container.querySelector('[data-forgot-sent]')).toBeNull()
  })

  it('offers a way back to sign in', () => {
    const { container } = render(<ForgotPasswordForm />)
    const hrefs = Array.from(container.querySelectorAll('a')).map((a) => a.getAttribute('href'))
    expect(hrefs).toContain('/login')
  })
})

describe('reset password', () => {
  it('treats a missing token exactly like a bad one', () => {
    const { container } = render(<ResetPasswordForm />)
    expect(container.querySelector('[data-reset-invalid]')).toBeTruthy()
    expect(container.textContent).toContain(INVALID)
    // and offers the way to get a working link
    const hrefs = Array.from(container.querySelectorAll('a')).map((a) => a.getAttribute('href'))
    expect(hrefs).toContain('/forgot-password')
  })

  it('renders the password fields when a token is present', () => {
    searchParams = new URLSearchParams('token=abc123')
    const { container } = render(<ResetPasswordForm />)
    expect(container.querySelector('#password')).toBeTruthy()
    expect(container.querySelector('#password_confirmation')).toBeTruthy()
  })

  it('shows one message for every kind of bad token', async () => {
    searchParams = new URLSearchParams('token=abc123')
    // expired, used, unknown and malformed all arrive as the same 400
    for (const detail of [
      'This password reset link is invalid or has expired. Please request a new one.',
      'something else entirely',
    ]) {
      resetPassword.mockRejectedValue(new ApiError(400, detail))
      const { container } = render(<ResetPasswordForm />)
      submit(container)
      await waitFor(() => expect(container.querySelector('[data-auth-error]')).toBeTruthy())
      expect(container.querySelector('[data-auth-error]')?.textContent).toBe(INVALID)
    }
  })

  it('shows validation problems verbatim, since they are the user own input', async () => {
    searchParams = new URLSearchParams('token=abc123')
    resetPassword.mockRejectedValue(
      new ApiError(422, 'password must be at least 10 characters'),
    )
    const { container } = render(<ResetPasswordForm />)
    submit(container)
    await waitFor(() => {
      expect(container.querySelector('[data-auth-error]')?.textContent).toBe(
        'password must be at least 10 characters',
      )
    })
  })

  it('confirms success and mentions that other sessions ended', async () => {
    searchParams = new URLSearchParams('token=abc123')
    resetPassword.mockResolvedValue({ message: 'ok' })
    const { container } = render(<ResetPasswordForm />)
    submit(container)

    await waitFor(() => expect(container.querySelector('[data-reset-done]')).toBeTruthy())
    expect(container.textContent).toMatch(/signed out/i)
    const hrefs = Array.from(container.querySelectorAll('a')).map((a) => a.getAttribute('href'))
    expect(hrefs).toContain('/login')
  })

  it('handles a server error without claiming the password changed', async () => {
    searchParams = new URLSearchParams('token=abc123')
    resetPassword.mockRejectedValue(new ApiError(500, 'internal error'))
    const { container } = render(<ResetPasswordForm />)
    submit(container)
    await waitFor(() => expect(container.querySelector('[data-auth-error]')).toBeTruthy())
    expect(container.querySelector('[data-reset-done]')).toBeNull()
  })

  it('never distinguishes expired from used from unknown in its copy', async () => {
    const { readFileSync } = await import('node:fs')
    const { join } = await import('node:path')
    const src = readFileSync(join(__dirname, 'reset-password-form.tsx'), 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, ' ')
      .replace(/\/\/[^\n]*/g, ' ')
      .toLowerCase()

    for (const leak of ['already used', 'token expired', 'no such token', 'unknown token']) {
      expect(src).not.toContain(leak)
    }
  })
})

describe('the reset screens store nothing', () => {
  it('reference no browser storage', async () => {
    const { readFileSync } = await import('node:fs')
    const { join } = await import('node:path')
    for (const file of ['forgot-password-form.tsx', 'reset-password-form.tsx']) {
      const src = readFileSync(join(__dirname, file), 'utf8')
      expect(src).not.toMatch(/localStorage|sessionStorage|document\.cookie/)
    }
  })
})
