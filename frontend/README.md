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
| `/` | Payables desk (home). `?payment=<id>` opens the evidence drawer. |
| `/payments/:id` | Redirects to the desk with that payment's drawer open. |
| `/approve` | Owner approval sheet (mobile-first) with slide-to-approve. |
| `/receipt/:batchId` | Settlement progress, then receipt. Add `?instant=1` to skip the animation. |
| `/fairness` | Fairness and harm panel. |
| `/network` | The corridor: latency per hop, tokens, model version, topology. |
| `/redteam` | Red-team results, 15 of 15 blocked. |
| `/tokens` | Design-token reference and component gallery. |

Add `?theme=dark` or `?theme=light` to any URL to force a theme (also saved to `localStorage`). The agent activity panel is toggled with the robot icon in the header and opens automatically when you expand a payment.

## Click-through demo

1. On the desk, expand **Warsaw Steel** → read the evidence → tick the call-back checklist → **Mark as verified**.
2. Expand **Nova Trade LLC** to see the shared-details mini-graph. Leave it on hold.
3. **Approve batch** → pick funding → slide to approve.
4. Watch the settlement progress, copy the transaction ID, open the explorer link.

## Project layout

```
src/
  api/          types, mock + live clients, ApiProvider (toggle), useAsync
  data/         demo payments, network, red-team, fairness, agent steps, token reference
  components/
    ui/         shadcn/ui primitives
    brand/      logo mark + wordmark
    layout/     AppShell (header, nav, theme + API toggles, agent panel)
    vouch/      PaymentCard, StatusChip, RiskTag, TrustMeter, EvidenceBar,
                VendorTimelineRow, EvidenceDrawer, NetworkMiniGraph,
                SlideToApprove, AgentActivityPanel, States (empty/error/skeleton)
  pages/        one file per route
  store/        PaymentsProvider (list + actions + batch), UiProvider
  theme/        ThemeProvider (light/dark)
  index.css     design tokens as CSS variables + Tailwind @theme
```

## Design tokens

All colors, radii, shadows and motion live as CSS variables in `src/index.css` (light under `:root`, dark under `.dark`) and are exposed to Tailwind via `@theme inline` (`bg-vouched-soft`, `text-attention`, `shadow-card`, `rounded-xl`, …). The `/tokens` route renders the full reference.

Status colors are never the only signal: every chip and tag carries an icon and text.
