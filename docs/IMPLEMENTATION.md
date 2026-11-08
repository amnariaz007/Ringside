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

### Not built yet

- Dispute copilot (evidence, draft, recommendation, approve and submit)
- Real LLM provider
- Render deploy and Workflow, login, git and LICENSE
- Two-seller network
