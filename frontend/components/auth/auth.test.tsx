/**
 * The sign-in surface.
 *
 * What these pin is the error handling, because that is where an auth screen
 * usually leaks: a stack trace on the page, or a message that tells an attacker
 * whether an address is registered. The backend deliberately refuses to
 * distinguish "no such account" from "wrong password", and the interface must
 * not undo that by inventing a friendlier message.
 */
import { render, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import { ApiError } from '@/services/api'

const push = vi.fn()
const replace = vi.fn()

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push, replace }),
  usePathname: () => '/datasets',
  useSearchParams: () => new URLSearchParams(''),
}))

const mutate = vi.fn()
vi.mock('swr', async () => {
  const actual = await vi.importActual<typeof import('swr')>('swr')
  return { ...actual, useSWRConfig: () => ({ mutate }) }
})

const login = vi.fn()
const registerFn = vi.fn()
vi.mock('@/services/api', async () => {
  const actual = await vi.importActual<typeof import('@/services/api')>('@/services/api')
  return {
    ...actual,
    api: { ...actual.api, login: (...a: unknown[]) => login(...a), register: (...a: unknown[]) => registerFn(...a) },
  }
})

import { AuthForm } from './auth-form'

beforeEach(() => {
  push.mockReset(); replace.mockReset(); mutate.mockReset()
  login.mockReset(); registerFn.mockReset()
})

function fill(form: HTMLElement, id: string, value: string) {
  const input = form.querySelector(`#${id}`) as HTMLInputElement
  input.value = value
  input.dispatchEvent(new Event('input', { bubbles: true }))
}

describe('sign in', () => {
  it('renders the fields a login needs and nothing more', () => {
    const { container } = render(<AuthForm mode="login" />)
    expect(container.querySelector('#email')).toBeTruthy()
    expect(container.querySelector('#password')).toBeTruthy()
    // a display name belongs to registration only
    expect(container.querySelector('#display_name')).toBeNull()
  })

  it('shows the backend message verbatim and never a stack trace', async () => {
    login.mockRejectedValue(new ApiError(401, 'invalid email or password'))
    const { container } = render(<AuthForm mode="login" />)

    container.querySelector('form')!.dispatchEvent(
      new Event('submit', { bubbles: true, cancelable: true }),
    )

    await waitFor(() => {
      const error = container.querySelector('[data-auth-error]')
      expect(error?.textContent).toBe('invalid email or password')
    })
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/Traceback|at Object\.|\.py:\d+|Error:/)
  })

  it('does not reveal whether an account exists', async () => {
    // whatever the reason, the message the user sees is the backend's single
    // generic one -- the UI must not add "no such user" of its own
    login.mockRejectedValue(new ApiError(401, 'invalid email or password'))
    const { container } = render(<AuthForm mode="login" />)
    container.querySelector('form')!.dispatchEvent(
      new Event('submit', { bubbles: true, cancelable: true }),
    )
    await waitFor(() => expect(container.querySelector('[data-auth-error]')).toBeTruthy())
    const text = (container.textContent ?? '').toLowerCase()
    expect(text).not.toContain('no such')
    expect(text).not.toContain('not registered')
    expect(text).not.toContain('unknown account')
  })

  it('reports a connection failure as a connection failure', async () => {
    login.mockRejectedValue(new TypeError('NetworkError'))
    const { container } = render(<AuthForm mode="login" />)
    container.querySelector('form')!.dispatchEvent(
      new Event('submit', { bubbles: true, cancelable: true }),
    )
    await waitFor(() => {
      expect(container.querySelector('[data-auth-error]')?.textContent).toMatch(
        /could not reach the Subterra API/i,
      )
    })
  })
})

describe('create account', () => {
  it('asks for a display name and states the password rule', () => {
    const { container } = render(<AuthForm mode="register" />)
    expect(container.querySelector('#display_name')).toBeTruthy()
    expect(container.textContent).toMatch(/at least 10 characters/i)
  })

  it('surfaces a duplicate registration plainly', async () => {
    registerFn.mockRejectedValue(
      new ApiError(409, 'an account with this email already exists'),
    )
    const { container } = render(<AuthForm mode="register" />)
    container.querySelector('form')!.dispatchEvent(
      new Event('submit', { bubbles: true, cancelable: true }),
    )
    await waitFor(() => {
      expect(container.querySelector('[data-auth-error]')?.textContent).toBe(
        'an account with this email already exists',
      )
    })
  })

  it('states that nothing beyond an account is collected', () => {
    const { container } = render(<AuthForm mode="register" />)
    expect(container.textContent).toMatch(/nothing else is collected/i)
  })
})

describe('the redirect target cannot leave the site', () => {
  it('only ever navigates to an internal path', async () => {
    login.mockResolvedValue({ user: { id: 'u1' } })
    const { container } = render(<AuthForm mode="login" />)
    fill(container, 'email', 'a@example.test')
    fill(container, 'password', 'correct-horse-battery')
    container.querySelector('form')!.dispatchEvent(
      new Event('submit', { bubbles: true, cancelable: true }),
    )
    await waitFor(() => expect(replace).toHaveBeenCalled())
    const target = replace.mock.calls[0]![0] as string
    expect(target.startsWith('/')).toBe(true)
    expect(target.startsWith('//')).toBe(false)
    expect(target).not.toMatch(/^https?:/)
  })
})

describe('the browser never stores the credential', () => {
  it('keeps no token in localStorage or sessionStorage', async () => {
    login.mockResolvedValue({ user: { id: 'u1' } })
    const { container } = render(<AuthForm mode="login" />)
    container.querySelector('form')!.dispatchEvent(
      new Event('submit', { bubbles: true, cancelable: true }),
    )
    await waitFor(() => expect(login).toHaveBeenCalled())
    expect(window.localStorage.length).toBe(0)
    expect(window.sessionStorage.length).toBe(0)
  })

  it('the auth sources reference no browser storage at all', async () => {
    const { readFileSync } = await import('node:fs')
    const { join } = await import('node:path')
    for (const file of ['auth-form.tsx', 'require-auth.tsx', 'account-menu.tsx']) {
      const src = readFileSync(join(__dirname, file), 'utf8')
      expect(src).not.toMatch(/localStorage|sessionStorage|document\.cookie/)
    }
  })
})
