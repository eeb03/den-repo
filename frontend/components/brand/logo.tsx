import { cn } from '@/lib/utils'

/**
 * SUBTERRA mark: a horizon line with scan waves descending into the subsurface,
 * converging on a single detected point. Pure geometry, scales cleanly.
 */
export function SubterraMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      fill="none"
      className={cn('size-7', className)}
      aria-hidden="true"
    >
      {/* surface horizon */}
      <line
        x1="3"
        y1="10"
        x2="29"
        y2="10"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        className="text-foreground"
      />
      {/* descending scan arcs */}
      <path
        d="M8 14 Q16 11 24 14"
        stroke="var(--primary)"
        strokeWidth="1.5"
        strokeLinecap="round"
        opacity="0.9"
      />
      <path
        d="M6 19 Q16 14.5 26 19"
        stroke="var(--primary)"
        strokeWidth="1.5"
        strokeLinecap="round"
        opacity="0.6"
      />
      <path
        d="M4.5 24 Q16 18 27.5 24"
        stroke="var(--primary)"
        strokeWidth="1.5"
        strokeLinecap="round"
        opacity="0.32"
      />
      {/* detected target */}
      <circle cx="16" cy="22" r="2.1" fill="var(--primary)" />
      <circle cx="16" cy="22" r="4.2" stroke="var(--primary)" strokeWidth="1" opacity="0.4" />
    </svg>
  )
}

export function SubterraLogo({
  className,
  showText = true,
  size = 'md',
}: {
  className?: string
  showText?: boolean
  size?: 'sm' | 'md' | 'lg'
}) {
  const markSize = size === 'lg' ? 'size-9' : size === 'sm' ? 'size-6' : 'size-7'
  const textSize = size === 'lg' ? 'text-xl' : size === 'sm' ? 'text-sm' : 'text-base'
  return (
    <span className={cn('inline-flex items-center gap-2.5', className)}>
      <SubterraMark className={markSize} />
      {showText && (
        <span
          className={cn(
            'font-semibold tracking-[0.18em] text-foreground',
            textSize,
          )}
        >
          SUBTERRA
        </span>
      )}
    </span>
  )
}
