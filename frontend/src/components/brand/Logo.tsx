import { cn } from '@/lib/utils'

export function VouchMark({ size = 20, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden="true" className={cn('shrink-0', className)}>
      <rect x="0.5" y="0.5" width="31" height="31" rx="6.5" className="fill-surface-2 stroke-border" />
      <path d="M9.5 16.5 14 21 23 11.5" className="stroke-accent-cool" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export function Logo({ className, size = 20, withWordmark = true }: { className?: string; size?: number; withWordmark?: boolean }) {
  return (
    <span className={cn('inline-flex items-center gap-2', className)}>
      <VouchMark size={size} />
      {withWordmark && <span className="text-sm font-semibold tracking-[0.12em] text-foreground uppercase">Vouch</span>}
    </span>
  )
}
