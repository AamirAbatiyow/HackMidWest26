/** Design-token reference, mirrored from src/index.css. Single source for the Tokens view and the PR. */

export interface ColorToken {
  name: string
  cssVar: string
  tailwind: string
  dark: string
  light: string
  role: string
}

export const COLOR_TOKENS: { group: string; tokens: ColorToken[] }[] = [
  {
    group: 'Surfaces',
    tokens: [
      { name: 'background', cssVar: '--background', tailwind: 'bg-background', dark: '#0B0D10', light: '#FAFBFC', role: 'Canvas' },
      { name: 'surface-1', cssVar: '--surface-1', tailwind: 'bg-surface-1', dark: '#0F1216', light: '#FFFFFF', role: 'Group rows, inputs, panels' },
      { name: 'surface-2', cssVar: '--surface-2', tailwind: 'bg-surface-2', dark: '#13171C', light: '#F3F5F7', role: 'Row hover, popovers' },
      { name: 'surface-3', cssVar: '--surface-3', tailwind: 'bg-surface-3', dark: '#181D23', light: '#E9ECEF', role: 'Active chip, palette selection' },
      { name: 'border', cssVar: '--border', tailwind: 'border-border', dark: '#1F242B', light: '#DDE2E8', role: 'Hairlines (1px) everywhere' },
      { name: 'input', cssVar: '--input', tailwind: 'border-input', dark: '#272D35', light: '#CFD6DE', role: 'Checkbox and field borders' },
    ],
  },
  {
    group: 'Text',
    tokens: [
      { name: 'foreground', cssVar: '--foreground', tailwind: 'text-foreground', dark: '#E6E8EB', light: '#14181D', role: 'Primary text, money' },
      { name: 'muted-foreground', cssVar: '--muted-foreground', tailwind: 'text-muted-foreground', dark: '#8B949E', light: '#5F6B78', role: 'Labels, meta, hints (AA)' },
    ],
  },
  {
    group: 'Accent · one cool color',
    tokens: [
      { name: 'accent-cool', cssVar: '--accent-cool', tailwind: 'text-accent-cool', dark: '#6EA8FE', light: '#2563EB', role: 'Selection, focus, primary button, live dot' },
      { name: 'accent-cool-soft', cssVar: '--accent-cool-soft', tailwind: 'bg-accent-cool-soft', dark: 'rgb(110 168 254 / .12)', light: 'rgb(37 99 235 / .10)', role: 'Checked row, bulk toolbar' },
    ],
  },
  {
    group: 'Risk · amber and red only',
    tokens: [
      { name: 'amber', cssVar: '--amber', tailwind: 'text-amber', dark: '#E2A33B', light: '#9A6400', role: 'Quick check, verify, concern bars, BANK-CHG, DUP-SPLIT' },
      { name: 'amber-soft', cssVar: '--amber-soft', tailwind: 'bg-amber-soft', dark: 'rgb(226 163 59 / .12)', light: 'rgb(154 100 0 / .10)', role: 'Verify tag fill' },
      { name: 'red', cssVar: '--red', tailwind: 'text-red', dark: '#E5574F', light: '#C2322A', role: 'UNREC ring, shared-detail nodes, errors' },
      { name: 'red-soft', cssVar: '--red-soft', tailwind: 'bg-red-soft', dark: 'rgb(229 87 79 / .12)', light: 'rgb(194 50 42 / .08)', role: 'Error state fill' },
      { name: 'vouched', cssVar: '--vouched', tailwind: 'text-vouched', dark: '#A7B0BA', light: '#4B5563', role: 'Vouched tag and row border · neutral by design' },
    ],
  },
]

export const TYPE_TOKENS = [
  { name: 'text-2xs', px: '10 / 14', className: 'text-2xs', sample: 'COLUMN LABEL', note: 'caps labels, shortcut hints, tag codes' },
  { name: 'text-xs', px: '11 / 16', className: 'text-xs', sample: 'Due Oct 14 · 3d', note: 'meta, status tags, invoice IDs' },
  { name: 'text-sm', px: '12 / 18', className: 'text-sm', sample: 'Bank account changed 2 days ago', note: 'table cells, body' },
  { name: 'text-base', px: '13 / 20', className: 'text-base', sample: 'Warsaw Steel Sp. z o.o.', note: 'html default, panel headings' },
  { name: 'text-lg', px: '14 / 20', className: 'text-lg', sample: 'Owner approval', note: 'rare · dialog titles' },
  { name: 'num', px: 'inherit', className: 'num', sample: '$12,000 · WS-2026-0917', note: 'JetBrains Mono, tabular numerals for all money and IDs' },
  { name: 'label-caps', px: '10 / 14', className: 'label-caps', sample: 'Vendor history', note: '0.06em tracking, muted' },
]

export const FONT_TOKENS = [
  { name: '--font-sans', value: 'Geist Variable', use: 'Labels, vendor names, body' },
  { name: '--font-mono', value: 'JetBrains Mono Variable', use: 'Money, IDs, timestamps, codes, hints' },
]

export const SPACING_TOKENS = [
  { name: '4px grid', value: '4 · 8 · 12 · 16 · 24', use: 'All padding and gaps' },
  { name: '--spacing-topbar', value: '36px', use: 'Top bar' },
  { name: '--spacing-strip', value: '24px', use: 'Bottom status strip' },
  { name: 'summary / filter rows', value: '32px', use: 'Lines above tables' },
  { name: 'table header', value: '28px', use: 'Sticky column headers, group rows' },
  { name: '--spacing-row', value: '30px', use: 'Table rows, checklist, history, evidence bars' },
  { name: '--spacing-row-sm', value: '28px', use: 'Palette items, compact lists' },
  { name: '--spacing-panel', value: '40%', use: 'Docked right detail panel' },
]

export const RADIUS_TOKENS = [
  { name: '--radius-xs', value: '2px', use: 'Tags, checkboxes, buttons, inputs, nodes' },
  { name: '--radius-md', value: '3px', use: 'shadcn default (--radius)' },
  { name: '--radius-lg', value: '4px', use: 'Dialogs, popovers, figures · maximum anywhere' },
]

export const ELEVATION_TOKENS = [
  { name: '--shadow-pop', value: '0 0 0 1px var(--border)', use: 'Floating layers use a hairline, never a shadow' },
  { name: 'gradients / glows', value: 'none', use: 'Not used' },
]

export const MOTION_TOKENS = [
  { name: '--duration-fast', value: '100ms', use: 'Row hover, hint reveal' },
  { name: '--duration-base', value: '150ms', use: 'Feed line in' },
  { name: '--duration-slow', value: '200ms', use: 'Slider settle' },
  { name: '--ease-out-quart', value: 'cubic-bezier(.25, 1, .5, 1)', use: 'All eased motion' },
]
