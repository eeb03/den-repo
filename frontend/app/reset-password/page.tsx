import { Suspense } from 'react'
import type { Metadata } from 'next'
import { ResetPasswordForm } from '@/components/auth/reset-password-form'

export const metadata: Metadata = { title: 'Choose a new password — Subterra' }

export default function ResetPasswordPage() {
  // Suspense because the form reads the token from the query string.
  return (
    <Suspense>
      <ResetPasswordForm />
    </Suspense>
  )
}
