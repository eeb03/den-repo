import type { Metadata, Viewport } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Subterra Data Platform',
  description:
    'Ingestion, validation, fusion and evaluation of multimodal underground sensing datasets.',
}

export const viewport: Viewport = {
  colorScheme: 'dark',
  themeColor: '#0b0f14',
}

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="dark bg-background">
      <body className="font-sans antialiased">{children}</body>
    </html>
  )
}
