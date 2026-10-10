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

The app ships with built-in demo data (the six vendors from the brief). A typed client layer (`src/api/`) has two implementations behind one `VouchApi` interface:

- `mock.ts` — in-memory demo data with realistic latency.
- `live.ts` — the FastAPI backend at `VITE_API_URL` (default `http://localhost:8101`). Every call tries `/v1/<path>` first and falls back to the unversioned path on 404. Field names are normalized from `snake_case` or `camelCase`, and common status/risk spellings are mapped.

Mode is **auto** by default: the live `/v1/health` is probed every 5 s; when it answers, the app uses the live API and the status strip shows a `live` tag. When it does not, the app falls back to demo data and shows an amber `mock` tag whose hover text carries the reason. Force a mode from the command palette (`⌘K` → Data source) or with `VITE_API_MODE=live|mock`.

Endpoints used: `GET /v1/payments`, `GET /v1/payments/:id`, `POST /v1/payments/:id/{approve,hold,appeal}`, `POST /v1/batch/settle`, `GET /v1/netz` (latency p50/p95, tokens today, hops), `GET /v1/info` (active model, policy mode), `GET /v1/redteam`, `GET /v1/fairness`, `GET /v1/health`.

Duplicate / split links come from `duplicate_of` / `split_with` (payment id) on a payment, or a `relation: { kind, payment_id }` object.

## Routes

| Route | Screen |
|---|---|
| `/` | Payables queue (home). Dense, lane-grouped table with the detail panel docked at 40%; the first flagged row opens on load. `?payment=<id>` opens a specific one. `esc` shows the "Next up" summary instead of an empty panel. |
| `/payments/:id` | Redirects to the queue with that payment's panel open. |
| `/approve` | Owner approval: batch table + slide-to-approve. Reached from bulk approve, `a`, or the palette. |
| `/receipt/:batchId` | Settlement receipt. |
| `/fairness` | Harm ledger, parity by country, bounding rules. |
| `/network` | Topology with p50/p95 per hop, hop table, runtime (model, tokens, policy mode, last settlement ID). |
| `/redteam` | Red-team cases, 15 of 15 blocked, rules fired. |
| `/tokens` | Design-token reference (not in the top nav; reachable from the palette or Network). |

Add `?theme=dark` or `?theme=light` to any URL to force a theme (also saved to `localStorage`). Dark is the design target.

## Keyboard

`j` / `k` move (the panel follows) · `Enter` open · `x` select · `a` approve · `h` hold · `v` verify · `p` appeal · `/` search · `⌘K` palette · `f` agent log · `?` all shortcuts · `g` then `p a f n r t` to switch views.

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
