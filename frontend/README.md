# Vouch — frontend

Every payment, vouched for. This is the owner-facing app: a payment trust layer that checks and explains every payment before an irreversible stablecoin payout, without ever auto-denying a vendor.

Stack: React 19 · TypeScript · Vite · Tailwind CSS v4 · shadcn/ui (Radix) · React Router · sonner.

## Run it

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

Other scripts:

```bash
npm run build      # typecheck (tsc -b) + production build to dist/
npm run lint       # oxlint
npm run preview    # serve the production build
```

## Mock data vs. live API

The app ships with built-in demo data (the six vendors from the brief) and uses it by default. A typed client layer (`src/api/`) has two implementations behind one `VouchApi` interface:

| | |
|---|---|
| `src/api/mock.ts` | In-memory demo data with realistic latency. State resets on reload. |
| `src/api/live.ts` | `fetch` client for the FastAPI backend, with tolerant response normalisers. |

Switch between them two ways:

1. **In the app** — open the settings (gear icon, top right) and flip **Live API**. The choice is saved in `localStorage` (`vouch.apiMode`).
2. **Env vars** — copy `.env.example` to `.env.local`:

```bash
VITE_API_MODE=live                 # default mode on first load: mock | live
VITE_API_URL=http://localhost:8101 # backend base URL
```

Endpoints the live client calls:

```
GET  /health
GET  /payments
GET  /payments/{id}
POST /payments/{id}/approve   { note }
POST /payments/{id}/hold      { note }
POST /payments/{id}/appeal    { note }
POST /batch/settle            { payment_ids, funding: "now" | "scheduled" }
GET  /netz
GET  /redteam
GET  /fairness                (optional; falls back to the reference report on 404)
```

`live.ts` accepts both `snake_case` and `camelCase` field names and maps common status/risk spellings, so small backend schema changes should not break the UI. If the backend is unreachable the desk shows an error state with a retry; flipping the switch off returns to demo data.

## Routes

| Route | Screen |
|---|---|
| `/` | Payables queue (home). Dense, lane-grouped table. `?payment=<id>` opens the detail panel. |
| `/payments/:id` | Redirects to the queue with that payment's panel open. |
| `/approve` | Owner approval: batch table + slide-to-approve. Reached from bulk approve, `a`, or the palette. |
| `/receipt/:batchId` | Settlement receipt. |
| `/fairness` | Harm ledger, parity by country, bounding rules. |
| `/network` | Topology with p50/p95 per hop, hop table, runtime (model, tokens, policy mode, last settlement ID). |
| `/redteam` | Red-team cases, 15 of 15 blocked, rules fired. |
| `/tokens` | Design-token reference (not in the top nav; reachable from the palette or Network). |

Add `?theme=dark` or `?theme=light` to any URL to force a theme (also saved to `localStorage`). Dark is the design target.

## Keyboard

`j` / `k` move · `Enter` open · `x` select · `a` approve · `h` hold · `v` verify · `p` appeal · `/` search · `⌘K` palette · `f` agent log · `?` all shortcuts · `g` then `p a f n r t` to switch views.

## Click-through demo

1. On the queue, press `j` to **Warsaw Steel** and `Enter` → read the three factors → tick the call-back checklist → **Verify**.
2. Open **Nova Trade LLC** to see the shared-detail ring (bank, phone, address) in the panel. Leave it on hold.
3. Select the three vouched rows (`x`) → **Approve 3 ($13,200)** → pick funding → slide to approve.
4. Copy the transaction ID from the receipt; the settlement ID also appears on the Network tab.

## Project layout

```
src/
  api/          types, mock + live clients, ApiProvider (toggle), useAsync
  data/         demo payments, feed script, network, red-team, fairness, token reference
  components/
    ui/         shadcn/ui primitives
    vouch/      StatusChip, RiskTag, TrustMeter, EvidenceBar, VendorTimelineRow,
                SlideToApprove, Sparkline, Table (DenseTable/Th/Td/Block/PageFrame), States
    workspace/  Shell, TopBar, StatusBar, AgentFeed (rail), PaymentsTable,
                DetailPanel, RingGraph, DecisionMatrix, CommandPalette, dialogs
  pages/        one file per route
  store/        PaymentsProvider (list + actions + batch), UiProvider, useVisibleRows
  lib/          format, shortcuts, useGlobalShortcuts
  theme/        ThemeProvider (dark default, light)
  index.css     every design token, as CSS variables + Tailwind @theme
```

## Design tokens

Defined once in `src/index.css` and reused everywhere; nothing visual is set per screen. `/tokens` renders the live reference and `src/data/tokens.ts` mirrors it.

| Token | Dark | Use |
|---|---|---|
| `--background` | `#0B0D10` | canvas |
| `--surface-1/2/3` | `#0F1216` / `#13171C` / `#181D23` | group rows · hover · active chip |
| `--border` | `#1F242B` | 1px hairlines everywhere |
| `--foreground` / `--muted-foreground` | `#E6E8EB` / `#8B949E` | text · labels |
| `--accent-cool` (+ `-soft`) | `#6EA8FE` | the one accent: selection, focus, primary button |
| `--amber` (+ `-soft`) | `#E2A33B` | quick check · verify · concern bars · BANK-CHG · DUP-SPLIT |
| `--red` (+ `-soft`) | `#E5574F` | UNREC ring · shared-detail nodes · errors |
| `--vouched` | `#A7B0BA` | vouched tag, neutral by design |
| `--font-sans` / `--font-mono` | Geist · JetBrains Mono | labels · money, IDs, codes (`num` utility, tabular) |
| type scale | 10 / 11 / 12 / 13 / 14 px | `text-2xs` … `text-lg`; `label-caps` = 10px caps |
| spacing | 4px grid | `--spacing-topbar` 36 · `--spacing-strip` 24 · `--spacing-row` 30 · header 28 · `--spacing-panel` 40% |
| radii | 2 / 3 / 4 px | tags · default · dialogs (max) |
| elevation | none | `--shadow-pop` = 1px hairline; no gradients or glows |
| motion | 100 / 150 / 200 ms | `--ease-out-quart`; reduced-motion respected |

Status is never color alone: every tag carries text, and rows add a 2px left border. Copy never says "reject" or "denied"; the "never auto-denies" line appears only in the detail panel.
