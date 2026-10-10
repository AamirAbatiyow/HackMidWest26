import { Check, ChevronsRight, Loader2 } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import { cn } from '@/lib/utils'

interface SlideToApproveProps {
  label?: string
  confirmedLabel?: string
  onConfirm: () => void | Promise<void>
  disabled?: boolean
  busy?: boolean
  className?: string
}

const KNOB = 52
const PAD = 4

/**
 * Slide-to-approve with full keyboard support: Arrow Right/Up nudges, End or
 * Enter/Space confirms, Home resets. Announced via aria-valuetext.
 */
export function SlideToApprove({
  label = 'Slide to approve',
  confirmedLabel = 'Approved',
  onConfirm,
  disabled,
  busy,
  className,
}: SlideToApproveProps) {
  const trackRef = useRef<HTMLDivElement>(null)
  const [x, setX] = useState(0)
  const [max, setMax] = useState(0)
  const [dragging, setDragging] = useState(false)
  const [done, setDone] = useState(false)
  const startX = useRef(0)
  const startOffset = useRef(0)

  useEffect(() => {
    const el = trackRef.current
    if (!el) return
    const update = () => setMax(el.clientWidth - KNOB - PAD * 2)
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const complete = useCallback(async () => {
    if (done || disabled) return
    setDone(true)
    setX(max)
    await onConfirm()
  }, [done, disabled, max, onConfirm])

  const onPointerDown = (e: PointerEvent<HTMLButtonElement>) => {
    if (disabled || done) return
    e.currentTarget.setPointerCapture(e.pointerId)
    startX.current = e.clientX
    startOffset.current = x
    setDragging(true)
  }

  const onPointerMove = (e: PointerEvent<HTMLButtonElement>) => {
    if (!dragging) return
    const next = Math.max(0, Math.min(max, startOffset.current + (e.clientX - startX.current)))
    setX(next)
  }

  const onPointerUp = () => {
    if (!dragging) return
    setDragging(false)
    if (x >= max * 0.9) void complete()
    else setX(0)
  }

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (disabled || done) return
    const step = Math.max(8, max / 8)
    switch (e.key) {
      case 'ArrowRight':
      case 'ArrowUp':
        e.preventDefault()
        setX((v) => {
          const n = Math.min(max, v + step)
          if (n >= max * 0.98) void complete()
          return n
        })
        break
      case 'ArrowLeft':
      case 'ArrowDown':
        e.preventDefault()
        setX((v) => Math.max(0, v - step))
        break
      case 'Home':
        e.preventDefault()
        setX(0)
        break
      case 'End':
      case 'Enter':
      case ' ':
        e.preventDefault()
        void complete()
        break
    }
  }

  const progress = max > 0 ? x / max : 0

  return (
    <div
      ref={trackRef}
      className={cn(
        'relative h-[60px] w-full overflow-hidden rounded-full bg-primary text-primary-foreground shadow-card select-none',
        disabled && 'opacity-50',
        className,
      )}
      style={{ padding: PAD }}
    >
      <div
        aria-hidden="true"
        className="absolute inset-0 rounded-full bg-vouched transition-opacity duration-300"
        style={{ opacity: done ? 1 : progress * 0.9 }}
      />
      <span
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 flex items-center justify-center text-[15px] font-semibold tracking-[-0.01em] transition-opacity duration-150"
        style={{ opacity: done ? 1 : 1 - progress * 1.4 }}
      >
        {done ? (busy ? 'Sending…' : confirmedLabel) : label}
      </span>
      <button
        type="button"
        role="slider"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(progress * 100)}
        aria-valuetext={done ? confirmedLabel : `${Math.round(progress * 100)}% — press End or Enter to approve`}
        aria-disabled={disabled || done}
        disabled={disabled}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onKeyDown={onKeyDown}
        className={cn(
          'relative z-10 flex items-center justify-center rounded-full bg-background text-foreground shadow-md outline-none focus-visible:ring-3 focus-visible:ring-ring/60',
          'touch-none',
          !dragging && 'transition-transform duration-300 ease-[var(--ease-vouch)]',
          dragging ? 'cursor-grabbing' : 'cursor-grab',
        )}
        style={{ width: KNOB, height: KNOB, transform: `translateX(${x}px)` }}
      >
        {done ? (
          busy ? (
            <Loader2 className="size-5 animate-spin text-vouched" aria-hidden="true" />
          ) : (
            <Check className="size-5 text-vouched" aria-hidden="true" />
          )
        ) : (
          <ChevronsRight className="size-5" aria-hidden="true" />
        )}
      </button>
    </div>
  )
}
