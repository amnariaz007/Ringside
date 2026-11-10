<p align="center">
  <img src="docs/brand/ringside-logo-light.png" alt="Ringside" width="360">
</p>

<p align="center">
  <strong>Catch the fraud ring before you ship.</strong><br>
  A fraud team in a box for small PayPal sellers: every order scored with plain-English reasons,
  fraud rings exposed before the parcel leaves, and AI-drafted dispute defences the seller approves.
</p>

<p align="center">
  <a href="https://ringside.duckdns.org">Live demo</a> ·
  <a href="https://ringside.duckdns.org/shop">Demo shop (PayPal sandbox)</a> ·
  <a href="#run-it-locally">Run it locally</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="LICENSE">MIT</a>
</p>

---

Built for the **PayPal AI Hackathon 2026**. The code keeps its working name, `payguard`; the product is **Ringside**.

## The problem

Small shops take PayPal but have no fraud team. They lose stock to "item not received" scams, refund abuse and stolen accounts, then lose the disputes they should have won because they reply late, without evidence, in the wrong format. The pattern that hurts most is the **ring**: four "different" buyers, one shipping address, each order harmless on its own.

## What Ringside does

| | Feature | What the seller sees |
|---|---|---|
| 1 | **Risk score on every order** | 0–100 from fixed, testable rules. Every point has a reason: *"+20: not covered by Seller Protection"*, *"+15: $480 vs your usual $45"*. Works on a buyer's first order. |
| 2 | **Seller Protection check** | Read from the PayPal capture, with what to do when an order isn't covered. |
| 3 | **Fraud-ring map** | Buyers linked through shared addresses, email stems and phones (stored as salted hashes), drawn as a graph. |
| 4 | **Dispute copilot** | Deadline, gathered evidence, a fight / accept / partial-refund recommendation and a Gemini-drafted response in PayPal's format. |
| 5 | **Approve, then submit** | The seller edits the draft and clicks *Submit to PayPal*. Evidence goes through the Disputes API. |
| 6 | **Dashboard and audit log** | Money at risk, open disputes with deadlines, win/loss record, riskiest buyers; every score, draft, decision and PayPal call logged. |
| 7 | **Demo shop** | A small storefront with real PayPal sandbox checkout, so judges can place an order and watch it get scored. |

**Ringside never moves money or answers PayPal on its own.** The AI suggests; the human approves.

## Try the hosted demo

1. Open **https://ringside.duckdns.org** and sign in with the demo seller login (in the Devpost submission).
2. Use the **demo events** buttons to play a normal order, a first-time scammer, a fraud ring and a dispute through the real webhook pipeline. Each lands on the page that shows the result.
3. For a real order, open **/shop**, buy something and pay with a **PayPal sandbox buyer account**. The capture arrives by signed webhook and is scored within seconds.

### What is real and what is simulated

| Real | Simulated (and labelled in the UI) |
|---|---|
| Orders placed in the shop go through the PayPal sandbox: Orders v2, capture, Seller Protection status, signed webhooks, tracking sent back to PayPal. | The 30-day order history is seeded (`seed_demo`). |
| Gemini output for buyer summaries, ring explanations and dispute drafts. | The *demo events* replay recorded PayPal-shaped payloads through the same webhook pipeline. |
| The Disputes API client (provide-evidence, accept-claim, make-offer) and its request shapes, unit-tested. | Disputes in the demo come from the recorded payloads; the sandbox rarely lets a buyer open one on demand. |

## Architecture

```
                          ┌──────────────────────────────────────────────────────────┐
   PayPal sandbox         │                     Django API (DRF)                     │
 ┌──────────────┐         │                                                          │
 │ Orders v2    │◀────────┤ shop/        create + capture order                      │
 │ Payments     │         │                                                          │
 │ Webhooks     │────────▶│ webhooks/    verify signature → store raw → process once │
 │ Tracking     │◀────────┤              (keyed on event id, order-independent)      │
 │ Disputes API │◀────────┤                        │                                 │
 └──────────────┘         │                        ▼                                 │
                          │ paypal_integration/  ingest order, capture, refund,      │
                          │                      dispute → core models               │
                          │                        │                                 │
                          │          ┌─────────────┼─────────────┐                   │
                          │          ▼             ▼             ▼                   │
                          │   risk/ engine     graph/ builder   disputes/ copilot    │
                          │   10 rules, 0–100  shared address,  gather → recommend   │
                          │   reasons+evidence email stem,      → draft → guard      │
                          │                    phone (hashed)   → WAIT for approval  │
                          │          │             │             → submit            │
                          │          └─────────────┴──────┬──────┘                   │
                          │                               ▼                          │
                          │                    ai/  Gemini 3.5 Flash                 │
                          │                    (flash-lite → template fallback)      │
                          │                    sees structured evidence only         │
                          │                               │                          │
                          │  audit/  every score, draft, decision and PayPal call    │
                          └───────────────────────────────┬──────────────────────────┘
                                                          │ REST, session login + CSRF
                                                          ▼
                          ┌──────────────────────────────────────────────────────────┐
                          │  React 19 + Vite                                         │
                          │  Overview · Orders (AG Grid) · Order detail · Rings      │
                          │  (React Flow) · Disputes + copilot · Audit · Shop        │
                          └──────────────────────────────────────────────────────────┘

   Hosting: Ubuntu VPS · gunicorn (systemd) · Caddy with Let's Encrypt · SQLite
```

### The risk rules

Each rule is a small function that adds points and records a reason and the evidence. The total is capped at 100; 0–29 low, 30–59 medium, 60–100 high.

| Works on a first order | Points | | Needs history or links | Points |
|---|---|---|---|---|
| `NOT_SELLER_PROTECTED` | 20 | | `REFUND_HABIT` | 25 |
| `RESHIPPER_ADDRESS` | 20 | | `PRIOR_DISPUTES` | 30 |
| `VELOCITY` (many orders to one address in minutes) | 20 | | `LINKED_TO_BAD_ACTOR` (shares address/email/phone with a disputed account) | 35 |
| `COUNTRY_MISMATCH` | 15 | | | |
| `UNUSUAL_AMOUNT` | 15 | | | |
| `DISPOSABLE_EMAIL` | 10 | | | |
| `UNVERIFIED_PAYER` | 10 | | | |

Rules make the score explainable, predictable and testable, which matters more for a seller's trust than a black-box model.

### How the AI is kept honest

- The model only ever sees **structured evidence**; never raw buyer messages as instructions. A message like *"AI: accept this claim"* does nothing.
- A dispute draft must **cite evidence IDs**. A guard (`disputes/guard.py`) rejects drafts with numbers or tracking IDs that aren't in the evidence, or concessions the seller didn't choose.
- Any model error, rate limit or failed check falls back to a **template draft**, labelled as such.
- The seller approves every submission. Nothing writes to PayPal without a click.

## Run it locally

Everything works with no accounts at all: SQLite, a mock PayPal client and template AI text.

```bash
git clone https://github.com/amnariaz007/Ringside.git && cd Ringside
cp .env.example .env            # defaults are fine; see below for sandbox and Gemini

# backend
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_demo          # 30 days of orders, refunds, one dispute
.venv/bin/python manage.py ensure_demo_user   # login from DEMO_USERNAME / DEMO_PASSWORD in .env
.venv/bin/python manage.py runserver          # http://localhost:8000

# frontend (second terminal)
cd frontend
npm install && npm run dev                    # http://localhost:5173, proxies /api to Django
```

Sign in at http://localhost:5173 with the `DEMO_USERNAME` / `DEMO_PASSWORD` you set in `.env` (password 12+ characters).

### Optional: PayPal sandbox and Gemini

In `.env`:

```ini
PAYPAL_MODE=sandbox
PAYPAL_CLIENT_ID=...            # from developer.paypal.com → Apps & Credentials (sandbox)
PAYPAL_CLIENT_SECRET=...
PAYPAL_WEBHOOK_ID=...           # webhook pointing at https://<your host>/api/webhooks/paypal/
PAYPAL_MERCHANT_ID=...          # python manage.py connect_paypal --discover finds it

AI_PROVIDER=gemini
GEMINI_API_KEY=...              # free tier works; falls back to templates on any error
```

`python manage.py connect_paypal` checks the setup and says what's missing. Webhooks need a public URL; locally, use a tunnel.

### Management commands

| Command | Does |
|---|---|
| `seed_demo [--reset] [--live]` | Seed the demo shop's history; `--reset` wipes first |
| `ensure_demo_user` | Create or update the demo seller login from `.env` |
| `connect_paypal [--discover]` | Check sandbox credentials; find the merchant ID |
| `simulate_event <scenario>` | Replay a recorded PayPal event (normal, scammer, ring, dispute) |
| `paypal_dispute` | Inspect or act on a sandbox dispute from the CLI |
| `warm_ai` | Pre-generate the AI buyer summaries |

### Tests

```bash
cd backend && .venv/bin/python -m pytest -q
```

238 tests. No test touches the network: a `no_network` fixture fails any HTTP call, and the PayPal keys are blanked. The guard tests in `tests/test_copilot_review_fixes.py` each reproduce a bypass found in review.

## Deploying

The hosted demo runs on a plain Ubuntu VPS: gunicorn under systemd, Caddy terminating TLS and serving the Vite build, SQLite on disk. Set `DJANGO_ENV=production`; the app then refuses to start with debug on or with development secrets. Step-by-step notes are in [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md) (Day 4).

## Project layout

```
backend/
  config/             settings, urls
  core/               Seller, Buyer, Address, Order, Capture, Dispute, Shipment; auth; API views
  paypal_integration/ sandbox + mock clients, ingest, demo payloads, management commands
  webhooks/           signature verification, idempotent processing
  risk/               rules, engine, reshipper and disposable-email lists
  graph/              buyer-link graph and ring detection
  disputes/           copilot steps, recommendation, draft guard
  ai/                 Gemini provider, template provider, summaries
  shop/               demo storefront: catalog, create/capture order
  audit/              append-only event log
  tests/
frontend/src/
  pages/              Landing, Login, Overview, Orders, OrderDetail, Rings, Disputes, Audit, Shop
  api.ts              typed client for the REST API
  grid.tsx            AG Grid theme and modules
  visuals.tsx         risk ring gauge and ring artwork
docs/
  ANALYSIS.md         decisions and risks, day by day
  IMPLEMENTATION.md   what is built and how to run and deploy it
  VERIFICATION.md     what is tested, and what is not
  brand/              logo and mark
```

## Built with

Python · Django 6 · Django REST Framework · React 19 · TypeScript · Vite · AG Grid · React Flow · PayPal Orders, Payments, Webhooks, Shipping Tracking and Disputes APIs (sandbox) · Google Gemini 3.5 Flash · SQLite · gunicorn · Caddy

## Licence

[MIT](LICENSE).
