'use client'

import { cn } from '@/lib/utils'
import type { ImportFormats } from '@/types/subterra'

/**
 * What the platform will do with this file, decided BEFORE it is uploaded.
 *
 * Three answers, kept apart deliberately. "Supported" and "unknown" are the
 * obvious two; the third exists because `converters/registry.py` keeps a
 * `KNOWN_UNSUPPORTED_FORMATS` map precisely so ingestion can say "this is a
 * GSSI XML sidecar and no adapter reads it" instead of skipping the file in
 * silence. Collapsing that into "unsupported" would throw away the more useful
 * half of the answer: the platform knows exactly what the file is.
 *
 * The verdict is computed from the registry the backend serves. There is no
 * extension list in this file, and there must never be one -- a second copy
 * would drift and start promising formats nobody can read.
 */
export type Verdict =
  | { kind: 'supported'; extension: string }
  | { kind: 'recognized_unsupported'; extension: string; description: string }
  | { kind: 'unknown'; extension: string }
  | { kind: 'too_large'; extension: string; limitBytes: number }

export function extensionOf(filename: string): string {
  const dot = filename.lastIndexOf('.')
  return dot === -1 ? '' : filename.slice(dot).toLowerCase()
}

export function classify(
  file: { name: string; size: number },
  formats: ImportFormats,
): Verdict {
  const extension = extensionOf(file.name)
  if (file.size > formats.max_upload_bytes) {
    return { kind: 'too_large', extension, limitBytes: formats.max_upload_bytes }
  }
  if (formats.supported.includes(extension)) return { kind: 'supported', extension }
  const known = formats.recognized_unsupported.find((r) => r.extension === extension)
  if (known) {
    return {
      kind: 'recognized_unsupported',
      extension,
      description: known.description,
    }
  }
  return { kind: 'unknown', extension }
}

const COPY: Record<Verdict['kind'], { label: string; tone: string }> = {
  supported: { label: 'Readable', tone: 'text-prov-measured border-prov-measured/40' },
  recognized_unsupported: {
    label: 'No adapter',
    tone: 'text-warning border-warning/40',
  },
  unknown: { label: 'Unknown format', tone: 'text-muted-foreground border-border' },
  too_large: { label: 'Too large', tone: 'text-destructive border-destructive/40' },
}

export function FormatVerdict({
  verdict,
  className,
}: {
  verdict: Verdict
  className?: string
}) {
  const { label, tone } = COPY[verdict.kind]
  return (
    <div data-verdict={verdict.kind} className={cn('space-y-1.5', className)}>
      <span
        className={cn(
          'inline-flex items-center gap-2 rounded-md border px-2 py-1 font-mono text-[11px] uppercase tracking-[0.16em]',
          tone,
        )}
      >
        {label}
      </span>
      <p className="text-xs leading-relaxed text-muted-foreground">
        {verdict.kind === 'supported' && (
          <>
            <code className="font-mono text-foreground">{verdict.extension}</code> is
            read by a registered converter. It will be converted, validated and
            registered.
          </>
        )}
        {verdict.kind === 'recognized_unsupported' && (
          <>
            Recognised format — no adapter available.{' '}
            <code className="font-mono text-foreground">{verdict.extension}</code> is a{' '}
            {verdict.description}. The platform can name it but cannot read it, so it
            will not be imported.
          </>
        )}
        {verdict.kind === 'unknown' && (
          <>
            Unknown format. Nothing in the converter registry claims{' '}
            <code className="font-mono text-foreground">
              {verdict.extension || '(no extension)'}
            </code>
            , and the platform will not guess at its contents.
          </>
        )}
        {verdict.kind === 'too_large' && (
          <>
            Above the {Math.round(verdict.limitBytes / (1024 * 1024 * 1024))} GB upload
            limit for this deployment.
          </>
        )}
      </p>
    </div>
  )
}
