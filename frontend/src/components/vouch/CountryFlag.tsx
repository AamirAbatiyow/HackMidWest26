import type { CountryCode } from '@/api/types'
import { COUNTRY_LABELS } from '@/lib/countries'
import { cn } from '@/lib/utils'

interface CountryFlagProps {
  country: CountryCode
  className?: string
  /** Width in px; height follows 3:2. */
  size?: number
}

/**
 * Simplified inline SVG flags so they render identically on every platform
 * (emoji flags are missing on several desktop OSes).
 */
export function CountryFlag({ country, className, size = 20 }: CountryFlagProps) {
  const h = Math.round((size * 2) / 3)
  const common = {
    width: size,
    height: h,
    viewBox: '0 0 30 20',
    role: 'img' as const,
    'aria-label': `${COUNTRY_LABELS[country]} flag`,
    className: cn('shrink-0 rounded-[3px] ring-1 ring-foreground/10', className),
  }

  switch (country) {
    case 'MX':
      return (
        <svg {...common}>
          <rect width="10" height="20" fill="#0B6B3A" />
          <rect x="10" width="10" height="20" fill="#F4F4F2" />
          <rect x="20" width="10" height="20" fill="#C8362D" />
          <circle cx="15" cy="10" r="2.4" fill="#8B5A2B" />
        </svg>
      )
    case 'PL':
      return (
        <svg {...common}>
          <rect width="30" height="10" fill="#F4F4F2" />
          <rect y="10" width="30" height="10" fill="#D22F3A" />
        </svg>
      )
    case 'BR':
      return (
        <svg {...common}>
          <rect width="30" height="20" fill="#1E8A4C" />
          <path d="M15 2.5 27 10 15 17.5 3 10Z" fill="#F2C94C" />
          <circle cx="15" cy="10" r="4.2" fill="#2B4A9C" />
        </svg>
      )
    case 'US':
    default:
      return (
        <svg {...common}>
          <rect width="30" height="20" fill="#F4F4F2" />
          {[0, 2, 4, 6, 8, 10, 12].map((i) => (
            <rect key={i} y={(i * 20) / 13} width="30" height={20 / 13} fill="#C8362D" />
          ))}
          <rect width="12" height={(7 * 20) / 13} fill="#2B4A9C" />
        </svg>
      )
  }
}
