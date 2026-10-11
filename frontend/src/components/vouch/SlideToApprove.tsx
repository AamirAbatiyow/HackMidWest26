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

const KNOB = 26
const PAD = 3

/**
 * Slide-to-approve. Keyboard: Arrow Right/Up nudges, End or Enter/Space
 * confirms, Home resets. Progress is announced via aria-valuetext.
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
    setX(Math.max(0, Math.min(max, startOffset.current + (e.clientX - startX.current))))
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
        'relative h-8 w-full overflow-hidden rounded-xs border border-accent-cool/50 bg-surface-1 select-none',
        disabled && 'opacity-50',
        className,
      )}
      style={{ padding: PAD }}
    >
      <div
        aria-hidden="true"
        className="absolute inset-0 bg-accent-cool transition-opacity duration-(--duration-slow)"
        style={{ opacity: done ? 1 : progress * 0.9 }}
      />
      <span
        aria-hidden="true"
        className={cn(
          'num pointer-events-none absolute inset-0 flex items-center justify-center text-xs transition-colors duration-(--duration-fast)',
          done || progress > 0.5 ? 'text-primary-foreground' : 'text-foreground',
        )}
        style={{ opacity: done ? 1 : 1 - progress * 0.6 }}
      >
        {done ? (busy ? 'Sending' : confirmedLabel) : label}
      </span>
      <button
        type="button"
        role="slider"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(progress * 100)}
        aria-valuetext={done ? confirmedLabel : `${Math.round(progress * 100)}% — End or Enter approves`}
        aria-disabled={disabled || done}
        disabled={disabled}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onKeyDown={onKeyDown}
        className={cn(
          'relative z-10 flex touch-none items-center justify-center rounded-xs bg-accent-cool text-primary-foreground outline-none focus-visible:ring-1 focus-visible:ring-ring',
          !dragging && 'transition-transform duration-(--duration-slow) ease-(--ease-out-quart)',
          dragging ? 'cursor-grabbing' : 'cursor-grab',
          done && 'bg-background text-accent-cool',
        )}
        style={{ width: KNOB, height: KNOB, transform: `translateX(${x}px)` }}
      >
        {done ? (
          busy ? <Loader2 className="size-3 animate-spin" aria-hidden="true" /> : <Check className="size-3" aria-hidden="true" />
        ) : (
          <ChevronsRight className="size-3" aria-hidden="true" />
        )}
      </button>
    </div>
  )
}
