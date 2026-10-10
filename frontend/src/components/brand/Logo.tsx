import { cn } from '@/lib/utils'

interface LogoProps {
  className?: string
  size?: number
  withWordmark?: boolean
}

export function VouchMark({ size = 28, className }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
      className={cn('shrink-0', className)}
    >
      <circle cx="16" cy="16" r="14" className="fill-primary" />
      <circle cx="16" cy="16" r="11" className="stroke-primary-foreground/35" strokeWidth="1" strokeDasharray="2 2.5" />
      <path
        d="M10.5 16.5 14.2 20.2 21.8 12.4"
        className="stroke-primary-foreground"
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

export function Logo({ className, size = 28, withWordmark = true }: LogoProps) {
  return (
    <span className={cn('inline-flex items-center gap-2.5', className)}>
      <VouchMark size={size} />
      {withWordmark && (
        <span className="font-heading text-[1.15rem] font-semibold tracking-[-0.02em] text-foreground">Vouch</span>
      )}
    </span>
  )
}
