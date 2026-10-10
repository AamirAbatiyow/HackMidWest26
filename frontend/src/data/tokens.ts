/** Design-token reference, mirrored from src/index.css. */

export interface ColorToken {
  name: string
  cssVar: string
  tailwind: string
  role: string
}

export const COLOR_TOKENS: { group: string; tokens: ColorToken[] }[] = [
  {
    group: 'Surfaces',
    tokens: [
      { name: 'Background', cssVar: '--background', tailwind: 'bg-background', role: 'Off-white page canvas (navy in dark)' },
      { name: 'Card', cssVar: '--card', tailwind: 'bg-card', role: 'Soft card surface' },
      { name: 'Muted', cssVar: '--muted', tailwind: 'bg-muted', role: 'Quiet fills, skeletons' },
      { name: 'Accent', cssVar: '--accent', tailwind: 'bg-accent', role: 'Hover and selected rows' },
      { name: 'Border', cssVar: '--border', tailwind: 'border-border', role: 'Hairlines' },
    ],
  },
  {
    group: 'Text and brand',
    tokens: [
      { name: 'Foreground', cssVar: '--foreground', tailwind: 'text-foreground', role: 'Deep navy body text' },
      { name: 'Muted foreground', cssVar: '--muted-foreground', tailwind: 'text-muted-foreground', role: 'Secondary text (AA on background)' },
      { name: 'Primary', cssVar: '--primary', tailwind: 'bg-primary', role: 'Navy buttons and the logo mark' },
      { name: 'Navy 900', cssVar: '--navy-900', tailwind: 'bg-navy-900', role: 'Brand navy' },
      { name: 'Navy 400', cssVar: '--navy-400', tailwind: 'bg-navy-400', role: 'Neutral meters and charts' },
      { name: 'Ivory', cssVar: '--ivory', tailwind: 'bg-ivory', role: 'Brand off-white' },
    ],
  },
  {
    group: 'Status',
    tokens: [
      { name: 'Vouched', cssVar: '--vouched', tailwind: 'text-vouched', role: 'Calm green: vouched, safe to pay' },
      { name: 'Vouched soft', cssVar: '--vouched-soft', tailwind: 'bg-vouched-soft', role: 'Green chip fill' },
      { name: 'Attention', cssVar: '--attention', tailwind: 'text-attention', role: 'Warm amber: needs your eyes' },
      { name: 'Attention soft', cssVar: '--attention-soft', tailwind: 'bg-attention-soft', role: 'Amber chip fill' },
      { name: 'Problem', cssVar: '--problem', tailwind: 'text-problem', role: 'Muted red: confirmed problems only' },
      { name: 'Problem soft', cssVar: '--problem-soft', tailwind: 'bg-problem-soft', role: 'Red fill for error states' },
    ],
  },
]

export const TYPE_TOKENS = [
  { name: 'Display', className: 'text-4xl font-semibold tracking-[-0.03em]', sample: '$48,200', note: '36px / 600 / tabular' },
  { name: 'Amount', className: 'text-[2rem] font-semibold tracking-[-0.02em] money', sample: '$12,000', note: '32px / 600 / tabular' },
  { name: 'Page title', className: 'text-[1.75rem] font-semibold tracking-[-0.02em]', sample: 'Payables desk', note: '28px / 600' },
  { name: 'Section title', className: 'text-xl font-semibold tracking-[-0.015em]', sample: 'Warsaw Steel Sp. z o.o.', note: '20px / 600' },
  { name: 'Card title', className: 'text-[15px] font-semibold', sample: 'Reyes Packaging', note: '15px / 600' },
  { name: 'Body', className: 'text-sm', sample: 'Bank details changed 2 days ago. A quick call clears this.', note: '14px / 400 / 1.5' },
  { name: 'Caption', className: 'text-xs text-muted-foreground', sample: 'Due Fri, Oct 16 · in 3d', note: '12px / 400' },
  { name: 'Mono', className: 'font-mono text-[13px]', sample: '0x7f3a…c21e', note: 'Transaction IDs' },
]

export const SPACING_TOKENS = [
  { name: 'space-1', px: 4 },
  { name: 'space-2', px: 8 },
  { name: 'space-3', px: 12 },
  { name: 'space-4', px: 16 },
  { name: 'space-5', px: 20 },
  { name: 'space-6', px: 24 },
  { name: 'space-8', px: 32 },
  { name: 'space-12', px: 48 },
]

export const RADIUS_TOKENS = [
  { name: 'radius-md', cssVar: '--radius-md', px: '9.6px', use: 'Tags, inputs' },
  { name: 'radius-lg', cssVar: '--radius-lg', px: '12px', use: 'Buttons, list rows' },
  { name: 'radius-xl', cssVar: '--radius-xl', px: '16px', use: 'Cards' },
  { name: 'radius-3xl', cssVar: '--radius-3xl', px: '24px', use: 'Approval sheet' },
  { name: 'full', cssVar: '—', px: '9999px', use: 'Chips, meters, slider' },
]

export const SHADOW_TOKENS = [
  { name: 'shadow-card', cssVar: '--shadow-card', use: 'Resting cards' },
  { name: 'shadow-card-hover', cssVar: '--shadow-card-hover', use: 'Hovered cards, panels' },
  { name: 'shadow-sheet', cssVar: '--shadow-sheet', use: 'Approval and receipt sheets' },
]

export const MOTION_TOKENS = [
  { name: 'duration-fast', value: '150ms', use: 'Color and opacity changes' },
  { name: 'duration-base', value: '200ms', use: 'Hover lifts, chips' },
  { name: 'duration-slow', value: '250ms', use: 'Panels, drawers' },
  { name: 'ease-vouch', value: 'cubic-bezier(0.2, 0.8, 0.2, 1)', use: 'All eased motion' },
]
