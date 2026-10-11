import type { LimeFactor, Payment } from '@/api/types'
import { classLabel, explanationFor, formatWeight, sortLime } from '@/lib/lime'
import { cn } from '@/lib/utils'

function LimeRow({ factor, max }: { factor: LimeFactor; max: number }) {
  const concern = factor.direction === 'concern'
  const pct = Math.round(Math.max(0.06, Math.min(1, Math.abs(factor.weight) / (max || 1))) * 100)
  return (
    <li className="grid grid-cols-[minmax(0,1fr)_56px] items-center gap-2 py-1" data-direction={factor.direction}>
      <div className="min-w-0">
        <p className={cn('truncate text-sm', concern ? 'text-foreground' : 'text-foreground/85')} title={factor.rawLabel !== factor.label ? factor.rawLabel : undefined}>
          {factor.label}
          <span className="sr-only">, {concern ? 'raises concern' : 'reassuring'}</span>
        </p>
        <div className="mt-1 h-1.5 w-full rounded-xs bg-foreground/10" aria-hidden="true">
          <span className={cn('block h-full rounded-xs', concern ? 'bg-red' : 'bg-green')} style={{ width: `${pct}%` }} />
        </div>
      </div>
      <span className={cn('num text-right text-xs tabular-nums', concern ? 'text-red' : 'text-green')} aria-label={`weight ${formatWeight(factor)}`}>
        {formatWeight(factor)}
      </span>
    </li>
  )
}

interface LimeExplanationProps {
  payment: Payment
  className?: string
  /** Cap the number of rows; the rest is still counted in the header. */
  limit?: number
}

/**
 * "Why VouchNet flagged this": LIME contributions sorted by weight, concerns red, reassuring green.
 * Pure presentational; no store access so it renders in tests and the explain dialog alike.
 */
export function LimeExplanation({ payment: p, className, limit }: LimeExplanationProps) {
  const { model, fromLime } = explanationFor(p)
  const flagged = p.status !== 'vouched'
  const sorted = sortLime(model.factors)
  const shown = limit ? sorted.slice(0, limit) : sorted
  const max = sorted.reduce((m, f) => Math.max(m, Math.abs(f.weight)), 0)
  const concerns = sorted.filter((f) => f.direction === 'concern').length
  const target = classLabel(model.targetClass)
  const scorer = model.scorer
  const scorerLabel = scorer === 'local-torch' || scorer === 'inference-service' ? 'VouchNet' : scorer === 'heuristic-fallback' ? 'VouchNet heuristic fallback' : scorer

  return (
    <section className={cn('border-b', flagged ? 'border-l-2 border-l-red' : 'border-l-2 border-l-green', className)} aria-labelledby={`lime-${p.id}`} data-testid="lime-explanation">
      <header className="px-3 pt-2.5">
        <div className="flex items-baseline justify-between gap-2">
          <h3 id={`lime-${p.id}`} className={cn('text-lg font-medium', flagged ? 'text-red' : 'text-green')}>
            {flagged ? 'Why it is held' : 'Why it is clear to pay'}
          </h3>
          <span className="num shrink-0 text-2xs text-muted-foreground">
            {concerns} concern{concerns === 1 ? '' : 's'} · {sorted.length - concerns} reassuring
          </span>
        </div>
        <p className="pt-0.5 text-xs text-muted-foreground">
          {fromLime ? (
            <>
              {flagged ? 'VouchNet flagged this. ' : 'VouchNet cleared this. '}
              Explained with <abbr title="Local Interpretable Model-agnostic Explanations" className="no-underline">LIME</abbr>, the open-source Python explainability library
              {target ? (
                <>
                  {' '}
                  · <span className="text-foreground/80">{target}</span> head
                </>
              ) : null}
              {scorerLabel ? <> · {scorerLabel}</> : null}
              {model.modelVersion ? <span className="num"> {model.modelVersion}</span> : null}
            </>
          ) : (
            <>{flagged ? 'VouchNet flagged this. ' : 'VouchNet cleared this. '}Factors from the screening model (LIME, the open-source Python explainability library, in live mode)</>
          )}
        </p>
      </header>
      <ol className="px-3 pt-1 pb-2">
        {shown.map((f) => (
          <LimeRow key={f.id} factor={f} max={max} />
        ))}
        {shown.length === 0 && <li className="py-1 text-xs text-muted-foreground">No model factors for this card.</li>}
      </ol>
      {limit && sorted.length > shown.length && <p className="px-3 pb-2 text-2xs text-muted-foreground">+{sorted.length - shown.length} more under More details</p>}
    </section>
  )
}
