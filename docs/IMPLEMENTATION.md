# Ringside (code name PayGuard): Implementation

What exists in the code, how it fits together, and how to run it. It's updated each build day.

---

## Run it (no accounts needed)

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_demo --reset --live   # demo shop + 4 live scenarios
.venv/bin/python manage.py runserver                  # http://localhost:8000/api/
.venv/bin/pytest                                      # backend tests
```

Run the dashboard (second terminal):

```bash
cd frontend && npm install && npm run dev             # http://localhost:5173 (proxies /api to :8000)
```

Play one event through the webhook pipeline on its own:

```bash
.venv/bin/python manage.py simulate_event normal    # low risk
.venv/bin/python manage.py simulate_event scammer   # high risk, 6 reasons
.venv/bin/python manage.py simulate_event ring      # high risk, linked to 3 bad accounts
.venv/bin/python manage.py simulate_event dispute   # "item not received" with an injection attempt
```

Configuration lives in environment variables; see [`.env.example`](../.env.example). The defaults are `PAYPAL_MODE=mock` and `AI_PROVIDER=template`.

---

## Day 1 (8 Nov): backend core ✅

### Layout

```
backend/
  config/              settings (env-driven), urls
  core/                Seller, Buyer, Address, Order, Capture, Refund, Dispute
                       normalize.py: email/phone hashing, address keys
                       serializers.py, views.py: read-only REST API
  risk/                rules.py: 10 pure rules + evaluate()
                       context.py: builds OrderFacts and RiskContext from the DB
                       engine.py: score_order(): persist, explain, audit
                       lists.py: disposable domains, reshipper keywords
  paypal_integration/  client.py: Mock / Sandbox client behind get_client()
                       payloads.py: PayPal-format JSON builders
                       ingest.py: PayPal JSON -> rows (idempotent)
                       demo.py: Juniper Lane Apparel seed + live scenarios
                       management/commands/: seed_demo, simulate_event
  webhooks/            WebhookEvent model, service.py pipeline, view
  ai/                  providers.py: AIProvider interface, TemplateProvider
  audit/               AuditEvent model + record() helper
  tests/               56 tests (see VERIFICATION.md)
```

### Data flow

```
PayPal (mock or sandbox)
   │ webhook POST /api/webhooks/paypal/
   ▼
webhooks.service.handle()
   1. parse JSON (400 if malformed)
   2. verify signature via client (400 + stored as unverified if forged)
   3. store WebhookEvent once, keyed on event id (duplicates return 200, no reprocessing)
   4. process by type:
        PAYMENT.CAPTURE.COMPLETED  -> client.get_order() -> ingest_order() -> score_order()
        PAYMENT.CAPTURE.REFUNDED   -> ingest_refund()
        CUSTOMER.DISPUTE.*         -> client.get_dispute() -> ingest_dispute()
      missing dependency (out of order) -> 503, so PayPal retries
   5. mark processed; audit everything
```

### Risk engine

`risk.rules.evaluate(OrderFacts, RiskContext)` runs 10 pure rules, caps the score at 100, and maps it to a level (0–29 low, 30–59 medium, 60+ high). The thresholds are constants at the top of [`rules.py`](../backend/risk/rules.py).

| Rule | Pts | Fires when |
|---|---|---|
| NOT_SELLER_PROTECTED | 20 | Capture's `seller_protection.status` is `NOT_ELIGIBLE` (an unknown status never fires) |
| COUNTRY_MISMATCH | 15 | Payer country ≠ shipping country (both known) |
| RESHIPPER_ADDRESS | 20 | Address text matches forwarder keywords |
| UNUSUAL_AMOUNT | 15 | ≥ 4× the shop's median, with ≥ 10 past orders |
| VELOCITY | 20 | ≥ 3 orders to one address within 10 minutes |
| DISPOSABLE_EMAIL | 10 | Domain is on the disposable list |
| UNVERIFIED_PAYER | 10 | `payment_source.paypal.account_status` is `UNVERIFIED` |
| REFUND_HABIT | 25 | ≥ 2 refunds in the buyer's last 5 orders |
| PRIOR_DISPUTES | 30 | ≥ 2 disputes in 60 days |
| LINKED_TO_BAD_ACTOR | 35 | ≥ 2 linked accounts with refunds or disputes, linked by a shared **address or phone** (an email stem alone doesn't count; added on day 2) |

History rules only count events **before** the order's own timestamp, so a score is exactly what the seller would have seen at that moment.

### PayPal client

| Method | Mock | Sandbox |
|---|---|---|
| `get_order` | Reads the `MockPayPalObject` table | `GET /v2/checkout/orders/{id}` |
| `get_dispute` | Reads the `MockPayPalObject` table | `GET /v1/customer/disputes/{id}` |
| `verify_webhook_signature` | Accepts only the mock signature | `POST /v1/notifications/verify-webhook-signature`, with the raw body spliced in byte-for-byte |
| OAuth | n/a | Client-credentials token, cached until 60 s before expiry |

### AI layer

The `AIProvider` interface currently has one implementation, `TemplateProvider`. It builds the explanation from the top three findings plus advice for that level. Real providers will implement the same methods and fall back to the template on any error.

### REST API

| Endpoint | Returns |
|---|---|
| `GET /api/health/` | Status plus the current PayPal and AI modes |
| `GET /api/orders/?level=high` | Orders with latest score, level and Seller Protection status |
| `GET /api/orders/{id}/` | The above plus the assessment: explanation and findings with evidence |
| `GET /api/disputes/` | Disputes with reason, status and response deadline |
| `POST /api/webhooks/paypal/` | The webhook receiver |

### Demo data ("Juniper Lane Apparel", all fictional; was "Lahore Threads" until day 2)

- 45 normal buyers, 60 orders over 30 days ($20–$80), 2 ordinary refunds
- Fraud ring accounts 1–3 sharing one Newark address, phones and an email stem: 2 refunds and 1 dispute lost
- Live: normal buyer (0, low), first-time scammer (90, high), ring account 4 (70, high), and an open "item not received" dispute with a prompt-injection message

### Not built yet (by plan)

- Graph builder API (day 2), React dashboard (days 2–3)
- Dispute copilot: evidence gathering, draft, recommendation, approve/submit (day 3). Needs a `Shipment`/tracking model for evidence.
- Real LLM provider, Render deploy, Workflows, audit log UI (day 4)
- Sandbox methods for refunds, provide-evidence, accept-claim, and Transaction Search
- Authentication (one demo login, planned for the deploy day)

---

## Day 2 (8 Nov): graph, dashboard API and React UI ✅

### New backend pieces

| File | What it does |
|---|---|
| `graph/builder.py` | Union-find clusters buyers who share an address or phone. Builds React Flow nodes (buyer, order, address, phone, email pattern, refund, dispute) and edges, plus ring stats: refunds, disputes lost, money lost, open high-risk money |
| `graph/views.py` | `GET /api/graph/rings/` (all clusters with 2+ buyers, worst first) and `GET /api/graph/buyers/<payer_id>/` (the cluster around one buyer) |
| `core/dashboard.py` | `GET /api/dashboard/`: money at risk (medium/high orders not yet refunded or disputed), open disputes with hours left, win/loss, riskiest buyers (score > 0), recent risky orders |
| `core/views.py` | `GET /api/audit/?actor=ai` (audit trail, filterable by actor, `paypal_id` and action) |
| `core/serializers.py` | Order detail now includes Seller Protection **advice** in plain words, a forwarder flag, refunds and disputes |
| `ai/providers.py` | `summarize_ring()`: template text such as "4 accounts share 1 shipping address, 2 phone numbers and 1 email pattern; together they caused 2 refunds (USD 139.00) and 1 lost dispute (USD 86.00)…" |

Phone and email-pattern nodes only appear when shared, and raw emails and phones never leave the backend; nodes are labelled "Shared phone #1" and "Email pattern @domain".

### Frontend (`frontend/`, React 19 + Vite + TypeScript)

| Page | Route | Shows |
|---|---|---|
| Overview | `/` | Money at risk, open disputes, orders scored, win/loss; "needs your attention"; dispute deadlines; ring summary; riskiest buyers |
| Orders | `/orders?level=high` | Table with risk badge, route (mismatch highlighted), Seller Protection pill; risk-level filter |
| Order detail | `/orders/:id` | Score bar, explanation, every finding with points, rule and evidence; Seller Protection advice; forwarder tag |
| Fraud rings | `/rings?buyer=<payer_id>` | Ring list and an interactive React Flow graph laid out in rows (evidence → buyer → order → outcome). Click a buyer to re-centre, an order to open it. Lazy-loaded |
| Disputes | `/disputes` | Reason, status, deadline (urgent under 72 h), amount. The copilot is added on day 3 |
| Audit log | `/audit` | Timeline filterable by actor (paypal, system, ai, seller) |

The sidebar badge shows `PayPal: mock · AI: template`, so simulated mode is always labelled honestly. Dark and light themes follow the system setting.

### Not built yet (as of the end of day 2)

- Dispute copilot, real LLM provider, git and LICENSE: **done on day 3**, see below
- Render deploy and Workflow, login
- Two-seller network

---

## Day 3 (8 Nov, evening): dispute copilot, Gemini, git and MIT ✅

### Repository

- `git init` on `main`, MIT [LICENSE](../LICENSE) (copyright amnariaz007), 2 commits so far. `docs/COMPETITIVE_STRATEGY.md` is git-ignored because it names competitors.
- **Not pushed yet.** The GitHub CLI isn't installed. To publish:
  `git remote add origin https://github.com/<you>/ringside.git && git push -u origin main`, then tick the licence in the repo's About section (a submission rule).

### How the copilot works

```
CUSTOMER.DISPUTE.CREATED webhook
  └─ prepare(dispute)            disputes/service.py (inline now; Render Workflow next)
       1. step_gather            disputes/evidence.py    → E1..En evidence + B1.. buyer messages (untrusted)
       2. step_recommend         disputes/recommend.py   → FIGHT / ACCEPT / PARTIAL_REFUND (rules, not AI)
       3. step_draft             ai provider + disputes/guard.py → draft that passes every check
     → case READY (nothing has been sent)

Seller opens /disputes/:id → reviews evidence, edits the text, picks an action
  → "Review and send" → inline confirm → POST /copilot/submit/ {action, text, confirm: true}
       FIGHT          → provide-evidence (PROOF_OF_FULFILLMENT with carrier + tracking; multipart)
       ACCEPT         → accept-claim
       PARTIAL_REFUND → make-offer (REFUND, the 30% offer)
     → re-fetch the dispute from PayPal → case SUBMITTED; every step in the audit log
```

### Evidence (`disputes/evidence.py`)

| Id | Kind | Source |
|---|---|---|
| E1 | Order | Order id, amount, date |
| E2 | Seller Protection | Capture's `seller_protection.status` and categories |
| E3 | Tracking | `Shipment` carrier and tracking number, and whether it went to the PayPal address (or "no tracking recorded", which weakens a defence) |
| E4 | Delivery | Carrier delivery date |
| E5 | Buyer history | Earlier orders from the same payer with no dispute or refund ("CE 3.0-style"; not the Visa rule itself) |
| E6, E7 | Risk / ring | Checkout risk score and linked accounts: **context only** |
| B1… | Buyer messages | Shown in a quarantined box; never evidence, never instructions |

### Recommendation rules (`disputes/recommend.py`)

| Situation | Recommendation |
|---|---|
| Item not received or unauthorised, delivered to the PayPal address with tracking | **Fight**: high confidence if Seller Protection covers it, medium if not |
| Delivered, but to a different address | Fight, low confidence |
| Shipped with tracking, delivery not confirmed | Fight, low confidence (send the tracking) |
| No tracking at all | **Accept** (PayPal will side with the buyer; avoids escalation) |
| Not as described | **Partial refund** of 30% (the buyer must agree) |
| Any other reason | Accept, low confidence: "review it yourself" |

Two hard rules: a ring link or risk score **never** produces Fight on its own, and buyer messages are never an input.

### AI layer (`ai/`)

| Piece | What it does |
|---|---|
| `TemplateProvider.draft_dispute` | Joins the evidence sentences word for word, each with its citation. Can't invent anything; always passes the guard |
| `GeminiProvider` | Gemini REST API (`x-goog-api-key` header, JSON output with a schema, temperature 0.2). Tasks: risk explanation, ring summary, dispute draft |
| `AICache` | Same model + task + input returns the stored answer, so free-tier rate limits can't break the demo |
| `WithFallback` | Any error, 429, timeout or failed check falls back to the template; the reasons go to `guard_notes` and the audit log |
| `disputes/guard.py` | Rejects drafts that cite unknown evidence, cite buyer messages, contain a long number (tracking, phone, ID) that isn't in the evidence, concede while the decision is Fight, echo "ignore previous instructions", or fall outside 60–2000 characters |

Enable Gemini: `AI_PROVIDER=gemini GEMINI_API_KEY=... python manage.py runserver` (free key from Google AI Studio).

### API

| Endpoint | Purpose |
|---|---|
| `GET /api/disputes/<id>/copilot/` | Case: evidence, buyer messages, recommendation, reasons, draft, status (prepared on first view if needed) |
| `POST /api/disputes/<id>/copilot/regenerate/` | Run the prepare steps again (blocked after submission) |
| `POST /api/disputes/<id>/copilot/submit/` | `{action, text, confirm: true}`. 400 without `confirm`, 409 for the wrong state, 502 if PayPal refuses (case → FAILED, can retry) |

### UI: `/disputes/:id`

Rules-based recommendation with evidence chips · an editable draft (source labelled "Draft built from evidence" or "AI draft · gemini:…") · a note when an AI draft was rejected · fight / accept / partial selector with a warning when it differs from the recommendation · an inline confirm step ("This can't be undone") · evidence list that highlights cited items · quarantined buyer message · after sending: "Sent to PayPal", the PayPal status and the exact text sent.

---

## Day 3b (8 Nov, night): login, Ledger redesign, AG Grid ✅

| Area | What changed |
|---|---|
| Login | `core/auth_views.py`: `GET /api/auth/me/` (also sets the CSRF cookie), `POST /api/auth/login/`, `POST /api/auth/logout/`. 10 failed attempts per IP per 15 minutes → 429. DRF requires a session on every API endpoint; `/api/health/` and `/api/webhooks/paypal/` stay public |
| Demo user | `python manage.py ensure_demo_user` reads `DEMO_USERNAME` / `DEMO_PASSWORD` (12+ characters) from `.env` |
| `.env` | Loaded automatically from `backend/.env` or the repo root (`python-dotenv`); real environment variables win |
| Theme | `frontend/src/index.css` rewritten as "Ledger": Fraunces, Inter and IBM Plex Mono (self-hosted via Fontsource), navy sidebar with icons and an open-disputes count, **content centred** in a 1160 px column |
| Ring motif | `visuals.tsx`: `RiskRing` gauge (tables, lists, order verdict), `RingsArt` backdrop (overview hero, login) |
| Overview | Navy hero with a plain-English summary of what needs attention, quick actions, and a ledger row of figures |
| AG Grid | `grid.tsx` registers Community modules once and defines `ledgerTheme` (`themeQuartz.withParams`). Orders: risk ring, buyer, "Why" chips, route, protection, amount; quick search; level filter; CSV export; pagination. Disputes: copilot state and deadline cells. Audit: actor filter, search, CSV export |
| Performance | Orders, Disputes, Audit and Rings load on demand; the main bundle is 345 kB |

## Day 4 (9 Nov): live on the VPS ✅

**URL:** https://ringside.duckdns.org (demo login: `DEMO_USERNAME` / `DEMO_PASSWORD` from `.env`)

| Piece | Where on the VPS (`root@173.212.238.249`) |
|---|---|
| Code | `/opt/payguard/app` (git-tracked files, rsynced) |
| Frontend build | `/opt/payguard/www` (`frontend/dist`) |
| Python venv | `/opt/payguard/venv` (requirements.txt + gunicorn 23.0.0) |
| Env file | `/opt/payguard/payguard.env` (mode 600; `DJANGO_ENV=production`, secret key and PII salt generated on the server, demo login, Gemini, PayPal) |
| Database | `/opt/payguard/data/db.sqlite3` (migrated, demo user created, `seed_demo` run) |
| Service | `payguard.service`: gunicorn, 3 workers, `127.0.0.1:8010`, runs as user `payguard` |
| Web | Caddy block appended to `/etc/caddy/Caddyfile` (backup `Caddyfile.bak-*` next to it): `/api/*` and `/admin*` → gunicorn, `/static/*` → `staticfiles`, everything else → the SPA with an `index.html` fallback |

**Redeploy after a change:**

```bash
cd frontend && npm run build && cd ..
git ls-files > /tmp/files.txt
rsync -az --files-from=/tmp/files.txt ./ root@173.212.238.249:/opt/payguard/app/
rsync -az --delete frontend/dist/ root@173.212.238.249:/opt/payguard/www/
ssh root@173.212.238.249 'chown -R payguard:payguard /opt/payguard/app && cd /opt/payguard/app/backend && \
  sudo -u payguard env $(grep -v "^#" /opt/payguard/payguard.env | xargs -d "\n") /opt/payguard/venv/bin/python manage.py migrate --noinput && \
  sudo -u payguard env $(grep -v "^#" /opt/payguard/payguard.env | xargs -d "\n") /opt/payguard/venv/bin/python manage.py collectstatic --noinput && \
  systemctl restart payguard'
```

Logs: `journalctl -u payguard -f`.

## Day 4b (9 Nov): real PayPal sandbox flow

Sandbox keys work (an OAuth token comes back). Before real sandbox events could reach the copilot, four things had to change.

| Gap | Fix | Where |
|---|---|---|
| Nowhere for a buyer to pay | **Juniper Lane storefront** at `/shop`: public, no login. Four products, a bag, PayPal JS SDK buttons. The server prices the cart, creates the order and captures it with our sandbox keys. The paid order is ingested and scored at once, and the capture webhook later does the same thing idempotently. The buyer never sees a risk score. | `backend/shop/`, `frontend/src/pages/Shop.tsx` |
| Real orders carry the real merchant ID, not `JUNIPERLANE01` | `PAYPAL_MERCHANT_ID` setting. The placeholder seller is relinked to it on first contact or by `connect_paypal`, so real orders join the seeded history and ring | `paypal_integration/sellers.py`, `ingest.py` |
| Seeded (simulated) records would be sent to PayPal in sandbox mode | `RoutingClient`: IDs in the mock store go to the simulator, everything else to the sandbox. Webhook signatures over HTTP are always checked by PayPal. The simulator delivers in-process with its own mock client. The seed registers its orders and disputes, and only ships or scores its own orders | `paypal_integration/client.py`, `demo.py` |
| No tracking for real orders | **Mark as shipped** card on the order page: carrier, tracking, delivered or signed-for. Saves the `Shipment`, sends tracking to PayPal (`POST /v2/checkout/orders/{id}/track`), and re-prepares the copilot of any open dispute on that order | `core/shipping.py`, `OrderViewSet.shipment`, `OrderDetail.tsx` |

Also:
- **Copilot start:** the copilot now also starts when a dispute reaches `WAITING_FOR_SELLER_RESPONSE` through an *update* (sandbox disputes often start as inquiries).
- **`manage.py connect_paypal [--discover]`:** checks the keys, webhook ID and merchant ID (yes/no only). `--discover` reads the business account's merchant ID from an unpaid $1 check order, then links the shop.
- **`manage.py paypal_dispute <id> --sync | --require-evidence | --adjudicate seller|buyer`:** syncs a dispute now, or uses PayPal's sandbox-only dispute controls.
- **`/api/health/`** adds `paypal_setup` with booleans only (keys, webhook ID, merchant ID).

### Going live on the sandbox (VPS)

1. Deploy this commit. The redeploy rsyncs `git ls-files`, so new files must be committed first.
2. On the VPS, re-seed **before any real order**: `manage.py seed_demo --reset`. The old seed didn't register its records as simulated.
3. PayPal Developer → app → **Webhooks → Add**:
   - URL: `https://ringside.duckdns.org/api/webhooks/paypal/`
   - Events: `PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.REFUNDED`, `CUSTOMER.DISPUTE.CREATED`, `CUSTOMER.DISPUTE.UPDATED`, `CUSTOMER.DISPUTE.RESOLVED`
4. In `/opt/payguard/payguard.env`:
   - `PAYPAL_MODE=sandbox`, the client ID and secret, and `PAYPAL_WEBHOOK_ID`
   - `PAYPAL_MERCHANT_ID`: run `connect_paypal --discover` to get it
   - Then restart and run `connect_paypal`; it should say "Ready".

### Day 4c (9 Nov): storefront polish
- **Ledger theme in the shop:** the shop now uses the same visual language as Ringside: navy band with a gold ring mark and bag counter, navy hero, serif headings, mono eyebrows, the same cards, and a navy footer.
- **Product images:** four original studio-style SVG illustrations in `frontend/public/shop/` (`jl-*.svg`, 9–13 KB each, drawn for this project, so there is no licensing question). The catalogue API returns an `image` path per product. If an image fails to load, the card falls back to the product's colour swatch.
- **Wording:** user-facing text no longer says "sandbox":
  - the shop banner is gone; checkout-closed messages are neutral
  - the login footer says "Connected to PayPal"
  - the sidebar badge shows `connected` or `demo data`
  - The README and video still say plainly that payments run on PayPal's test environment, as the hackathon rules require.

### Day 5 (10 Nov): demo told from the buyer's side
- **Order history and Items:** the shop remembers orders placed from this browser (`localStorage`), and the order page in Ringside shows an Items card and the shipping form with carrier and tracking.
- **Ring summaries off the request path:** `ai/summaries.py` writes the fraud-ring summary in a background thread and stores it in `AICache`; the page polls while `summary_pending` is true. `manage.py warm_ai` pre-writes it after a deploy. This removed the 60 s gunicorn timeout.
- **Shorter explanations:** Gemini is asked for two sentences, 35 words at most, stating the score as `<score>/100`; the template gives the main reason plus "N more signals".
- **Demo scenarios on the shop** (`DEMO_CONTROLS`, default on): a "Demo scenarios" strip at the bottom of `/shop` with four cards: normal buyer, risky buyer, fraud ring, buyer dispute. A click replays the matching simulated event (`POST /api/demo/<scenario>/`, the same pipeline as real webhooks) while the shop shows a feed of what the buyer did (names, amounts and addresses mirror `demo.py`), then links to the order or dispute in Ringside. The strip is labelled "Simulated buyers for the demo. Orders paid above are real PayPal payments." It needs a Ringside login in the same browser (the endpoint keeps `IsAuthenticated`); anonymous visitors get a message saying so. The sidebar Demo events menu was removed (one place to trigger scenarios is enough); Reset demo data is a link on the strip. The Orders grid now sorts by Placed (newest first) and Disputes by Opened, so a new event is always the top row. `GET /api/shop/` returns `demo_controls` so the strip hides when the flag is off.
- **Landing page** (`frontend/src/pages/Landing.tsx`, styles under `/* Landing page (editorial poster) */` in `index.css`): visitors who aren't signed in see a product page at `/`. Three concepts were produced in parallel (animated order feed, editorial poster, five-frame storyboard) and judged; the editorial poster won: masthead, a giant serif headline beside a 90/100 ring on a gold hairline grid, three numbered chapters (points ledger, engraved ring graph, evidence stack with draft reply and the struck-through injection quote), a navy colophon and the honesty line. Gold text uses a darker `--gold-ink` for contrast on paper. The sign-in form moved to `/login`; signed-in users who open `/login` are sent to the overview, and any deeper link still asks for sign-in first. The shop footer links to `/login`.
