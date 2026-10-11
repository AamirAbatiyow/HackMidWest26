# untangle — plan

> Keep this to one screen. Update it when scope changes; log big pivots in docs/DECISIONS.md.

## One-liner
Business vs personal transaction classification with explanations a bookkeeper can trust.

## The 30-second demo moment
<!-- The single thing a judge must see working live. Everything else is optional. -->

## Users and the problem
- Who:
- Pain today:
- What changes with this:

## Sponsor hooks (see docs/SPONSORS.md)
- AWS Strands: <!-- which agent pattern: single / graph / swarm / agents-as-tools, interrupts, MCP, A2A -->
- Akamai: <!-- inference endpoint + what runs on Linode/LKE -->
- Flex: <!-- fit with the Flex challenge -->

## Data
- Source / synthetic generator:
- Licensing note (also in data/DATA.md):

## Model
- Target / label:
- Baseline -> trained model:
- Metric that matters (and current value):
- Explanation shown to the user (LIME top factors):

## Agents and tools
- Agents:
- Tools (fixed ML tool, settlement, storage, MCP):
- Human approval points (interrupts):
- Policy rules (forbid/permit):

## API for the frontend
| Method | Path | Purpose |
|---|---|---|
| GET | /health | liveness |

## Build order (smallest end-to-end slice first)
1. [ ] Health checks + one fake end-to-end request
2. [ ] Model trained + /predict with explanation
3. [ ] Agent calls the model tool, human approval works
4. [ ] Settlement on mock -> testnet
5. [ ] Deployed on Akamai, demo script rehearsed

## Cut list (drop in this order if behind)
1.
2.

## Risks
-
