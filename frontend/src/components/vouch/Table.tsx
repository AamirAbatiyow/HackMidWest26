import type { ReactNode, TdHTMLAttributes, ThHTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

/** Dense table primitives: 28px header, 30px rows, hairline separators. */
export function DenseTable({ children, className, ...props }: React.TableHTMLAttributes<HTMLTableElement>) {
  return (
    <table className={cn('w-full table-fixed border-separate border-spacing-0 text-sm', className)} {...props}>
      {children}
    </table>
  )
}

export function Th({ children, className, right, width, ...props }: ThHTMLAttributes<HTMLTableCellElement> & { right?: boolean; width?: number }) {
  return (
    <th
      scope="col"
      style={width ? { width } : undefined}
      className={cn('label-caps sticky top-0 z-10 h-7 border-b bg-background px-2 text-left align-middle font-medium whitespace-nowrap', right && 'text-right', className)}
      {...props}
    >
      {children}
    </th>
  )
}

export function Td({ children, className, right, num, muted, ...props }: TdHTMLAttributes<HTMLTableCellElement> & { right?: boolean; num?: boolean; muted?: boolean }) {
  return (
    <td className={cn('h-row border-b px-2 py-0 align-middle whitespace-nowrap', right && 'text-right', num && 'num', muted && 'text-muted-foreground', className)} {...props}>
      {children}
    </td>
  )
}

/** Section header row inside a table (lane / group). */
export function GroupRow({ children, colSpan, className }: { children: ReactNode; colSpan: number; className?: string }) {
  return (
    <tr className={cn('bg-surface-1', className)}>
      <td colSpan={colSpan} className="h-7 border-y px-2 py-0 align-middle text-xs">
        {children}
      </td>
    </tr>
  )
}

/** Page frame shared by every non-payments view: summary line + body. */
export function PageFrame({ summary, aside, children, className }: { summary: ReactNode; aside?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div className={cn('flex min-h-0 min-w-0 flex-1 flex-col', className)}>
      <div className="flex h-8 shrink-0 items-center justify-between gap-4 border-b px-3">
        <p className="num truncate text-xs text-foreground/85">{summary}</p>
        {aside && <div className="num flex shrink-0 items-center gap-3 text-2xs text-muted-foreground">{aside}</div>}
      </div>
      <div className="min-h-0 flex-1 overflow-auto">{children}</div>
    </div>
  )
}

export function Block({ title, meta, children, className }: { title: string; meta?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cn('border-b', className)}>
      <div className="flex h-7 items-center justify-between gap-2 border-b bg-surface-1 px-3">
        <h2 className="text-xs font-medium">{title}</h2>
        {meta && <span className="num text-2xs text-muted-foreground">{meta}</span>}
      </div>
      {children}
    </section>
  )
}
