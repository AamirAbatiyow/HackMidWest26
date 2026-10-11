import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { QUEUE_PATH } from '@/lib/routes'

/** Route `/`: the wordmark alone on the canvas. Any click, Enter or Space opens the live queue. */
export function SplashPage() {
  const navigate = useNavigate()
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    ref.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
        e.preventDefault()
        navigate(QUEUE_PATH)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [navigate])

  return (
    <div
      ref={ref}
      role="button"
      tabIndex={0}
      aria-label="Vouch. Open the live queue"
      onClick={() => navigate(QUEUE_PATH)}
      className="flex h-dvh w-full cursor-pointer items-center justify-center bg-background text-foreground outline-none select-none"
    >
      {/* Trailing letter-spacing widens the box to the right; the left padding re-centres the glyphs. */}
      <h1 className="num animate-splash-in pl-[0.3em] text-3xl font-semibold tracking-[0.3em] uppercase">Vouch</h1>
    </div>
  )
}
