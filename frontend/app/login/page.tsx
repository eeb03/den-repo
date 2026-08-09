import { Suspense } from 'react'
import type { Metadata } from 'next'
import { AuthForm } from '@/components/auth/auth-form'

export const metadata: Metadata = { title: 'Sign in — Subterra' }

export default function LoginPage() {
  // Suspense because AuthForm reads the `next` search param.
  return (
    <Suspense>
      <AuthForm mode="login" />
    </Suspense>
  )
}
