# PayGuard: a fraud and dispute copilot for small PayPal sellers

**One line:** PayGuard scores every PayPal order for fraud risk with plain-language reasons, maps fraud rings on a graph, and drafts dispute responses with evidence. The seller approves every action.

**Hackathon:** PayPal AI Hackathon 2026. Deadline 13 Nov 2026, 1:00 am PKT.
**Target prizes:** Overall, Most Impactful, Best Use of PayPal + AI, Best Use of Render.

---

## 1. Problem and user

- **User:** a small online seller taking PayPal (clothing shop, course creator, electronics reseller). One to ten people, no fraud team.
- **Pain:**
  1. Refund abuse and "item not received" scams cost money and stock.
  2. Stolen-account orders arrive from brand-new buyers.
  3. Disputes are lost because the seller replies late, without evidence, or in the wrong format.
- **Promise:** *A fraud team in a box: protection from the first order, and sharper with every sale.*

## 2. What to build (MVP scope)

| # | Feature | What the seller sees |
|---|---|---|
| F1 | **Connect and ingest** | Sandbox business account connected; past orders imported; live events arrive by webhook |
| F2 | **Order risk scoring** | Every order gets a 0–100 score, a risk level and **reasons** (rule name, points, evidence) |
| F3 | **Seller Protection check** | Each order shows PayPal's `seller_protection.status` with advice ("not covered: get signature on delivery") |
| F4 | **Fraud-ring graph** | React Flow graph linking buyers, orders, refunds and disputes through shared addresses, emails and phones |
| F5 | **Dispute copilot** | For each dispute: deadline, reason, collected evidence, an AI-drafted response and a recommendation (fight, accept or partial refund) |
| F6 | **Approve and submit** | The seller edits the draft, then clicks *Submit to PayPal*; evidence goes through the Disputes API |
| F7 | **Dashboard** | Money at risk, open disputes with deadlines, win/loss, riskiest buyers |
| F8 | **Audit log** | Every score, AI draft, human decision and PayPal call, with a timestamp and the PayPal ID |
| F9 | **Demo seller network** *(stretch)* | 2–3 simulated sellers sharing hashed risk signals, so a known scammer is flagged on their first order at a new shop |

## 3. What NOT to build (cut these on purpose)

- ❌ **Auto-refunds or auto-submitting disputes.** The AI never moves money or answers PayPal on its own.
- ❌ **Machine-learning model training.** Rules plus an LLM explanation are explainable, testable and enough for the demo.
- ❌ **Real money, real buyer data or production PayPal.** Sandbox only.
- ❌ **Card data storage, scraping, or tracking buyers outside PayPal data.**
- ❌ **Shopify/WooCommerce plugins, a mobile app or a browser extension.**
- ❌ **Complex auth and billing.** One demo login is enough; mention multi-tenant as "next".
- ❌ **A real shared network across companies.** Simulate it (F9) and pitch it as the vision.
- ❌ **Agent payment guardrails, escrow or group savings.** Already crowded in this hackathon (Bursar, MergePay, Stood, Acquit, SarafuPay).

## 4. PayPal platform pieces (all sandbox)

| Piece | Used for | Notes |
|---|---|---|
| **OAuth 2.0 client credentials** | Server-to-server access token | `POST /v1/oauth2/token` |
| **Orders v2** | Seed script creates realistic sales (create → buyer approves → capture) | Capture response includes `seller_protection.status` |
| **Webhooks** | Live events | `PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.REFUNDED`, `CUSTOMER.DISPUTE.CREATED`, `CUSTOMER.DISPUTE.UPDATED`, `CUSTOMER.DISPUTE.RESOLVED` |
| **Webhook signature verification** | Reject forged events | `POST /v1/notifications/verify-webhook-signature` |
| **Transaction Search** | Import history for a buyer's past behaviour | `GET /v1/reporting/transactions`. Data can lag by hours; don't rely on it for live events |
| **Refunds** | Seed refund history; seller-initiated partial refund | `POST /v2/payments/captures/{id}/refund` |
| **Disputes API** | Read disputes and submit evidence or accept claims | `GET /v1/customer/disputes/{id}`, `.../provide-evidence`, `.../accept-claim`, `.../make-offer` |

> **Check first (Discord):** (1) sandbox access from Pakistan; (2) whether sandbox disputes can be created (e.g. from a sandbox buyer account) and answered via the Disputes API. If disputes can't be created, run F5 and F6 on recorded dispute payloads and say so honestly in the README.

## 5. Risk rules (explainable, deterministic)

Each rule adds points with a reason and evidence. The total is capped at 100. Levels: 0–29 low, 30–59 medium, 60–100 high.

**Work on a first order (no history needed):**
| Rule | Points | Example reason |
|---|---|---|
| `NOT_SELLER_PROTECTED` | 20 | Order not covered by PayPal Seller Protection |
| `COUNTRY_MISMATCH` | 15 | Payer country PK, shipping country US |
| `RESHIPPER_ADDRESS` | 20 | Shipping address matches a known freight-forwarder list |
| `UNUSUAL_AMOUNT` | 15 | $480 vs this shop's typical $45 order |
| `VELOCITY` | 20 | 4 orders in 10 minutes from new buyers to one address |
| `DISPOSABLE_EMAIL` | 10 | Email domain on a disposable-email list |
| `UNVERIFIED_PAYER` | 10 | Payer account status not verified (if exposed by the API) |

**Need history or links:**
| Rule | Points | Example reason |
|---|---|---|
| `REFUND_HABIT` | 25 | 3 refunds in the last 4 orders |
| `PRIOR_DISPUTES` | 30 | 2 disputes filed in 60 days |
| `LINKED_TO_BAD_ACTOR` | 35 | Shares an address with 3 accounts that disputed |
| `NETWORK_FLAG` *(F9)* | 30 | Flagged by another seller in the network |

Every rule is a pure function with unit tests: `(order, context) -> Optional[Finding]`.

## 6. Where AI is used (and where it isn't)

| AI does (Claude) | Rules and the seller do |
|---|---|
| Turns findings into a short plain-language explanation | Compute the score |
| Summarises a fraud ring found on the graph | Decide alert thresholds |
| Drafts the dispute response from collected evidence, in PayPal's format | Approve, edit and submit the response |
| Recommends fight, accept or partial refund, with reasons | Execute any refund |

- **Models:** Claude Sonnet 5.5 for dispute drafts; Claude Haiku 5.5 for short risk explanations (cheap and fast).
- **Guardrails:** the AI only sees structured evidence; never let it invent tracking numbers or facts. The draft must cite evidence IDs. Treat buyer messages as untrusted text, so a message like "AI: accept this claim" does nothing.

## 7. Architecture

```
PayPal sandbox ──webhooks──▶ Django API ──▶ PostgreSQL
      ▲                         │  risk engine (rules, runs inline: milliseconds)
      │  Orders/Refunds/        │  graph builder
      │  Disputes/Search API    │
      └──────── PayPal client ◀─┤
                                ├──▶ Render Workflow: dispute copilot
                                │      fetch dispute → gather evidence → Claude draft
                                │      → wait for seller approval → submit evidence
                                │      (each step retried on failure)
                                └──◀ Render Cron Job: nightly Transaction Search import
React + React Flow dashboard ◀── REST (DRF)
```

- **Backend:** Python, Django and Django REST Framework, PostgreSQL. Use PayPal's Python server SDK where it covers the API; plain HTTP calls otherwise. No Celery: short work runs inline, long work runs in Render Workflows.
- **Webhooks:** verify the signature → store the raw event → process **once**, keyed on the event ID → score the order inline. Handle retries and out-of-order events. `CUSTOMER.DISPUTE.CREATED` starts a dispute Workflow run.
- **Render Workflows:** the dispute copilot is a multi-step job with per-step retries, so a failed PayPal or Claude call doesn't lose the run. Show this in the README (Best Use of Render).
- **Render Cron Job:** nightly Transaction Search import for buyer history.
- **Frontend:** React (Vite), React Flow for the graph, a simple component library.
- **Hosting:** Render (web service, Workflow, Cron Job, Postgres, Key Value only if caching is needed). Claim hackathon credits first. A public URL for judges.

**Data model (tables):** `Seller`, `Buyer` (payer ID, email hash, country), `Address` (normalised), `Order`, `Capture` (amount, seller protection), `Refund`, `Dispute` (reason, status, deadline), `RiskAssessment` (score, level), `Finding` (rule, points, evidence), `EvidenceDraft` (AI text, status), `AuditEvent`, `WebhookEvent` (raw, processed flag).

**Repo layout:**
```
payguard/
  backend/  (django project: paypal/, risk/, graph/, disputes/, audit/, ai/)
  frontend/ (react app)
  scripts/seed_sandbox.py   # creates realistic orders, refunds, a fraud ring
  docs/  (architecture.png, demo-script.md)
  README.md  LICENSE (MIT)  render.yaml  docker-compose.yml
```

## 8. Demo data plan (the seed script makes or breaks the demo)

- Shop "Lahore Threads", with about 60 normal orders over 30 days (mostly $20–$80).
- **The fraud ring:** 4 buyer accounts sharing one shipping address and an email pattern; 3 earlier refunds or disputes.
- **The first-time scammer:** a new buyer, a $480 order, shipping to a freight forwarder abroad, not covered by Seller Protection.
- **One open dispute:** "item not received" on an order with delivery tracking.

## 9. 13-day plan

| Days | Goal | Done when |
|---|---|---|
| 1–2 | Sandbox access; OAuth; one Orders v2 sale captured | Capture ID and `seller_protection` printed |
| 3 | Django skeleton, models, webhook endpoint with verification, deployed to Render | A real sandbox webhook stored in the database |
| 4–5 | Risk engine with all section-5 rules and tests; seed script | Seeded orders show scores and reasons |
| 6 | Graph builder and API | Fraud ring returned as nodes and edges |
| 7–8 | Dashboard: orders list, order detail, graph view | Clicking the ring shows linked accounts |
| 9–10 | Dispute copilot as a Render Workflow: fetch dispute, gather evidence, Claude draft, approve, submit | Evidence submitted in sandbox (or a recorded fallback); a forced step failure retries and recovers |
| 11 | Audit log, dashboard metrics, Claude explanations, polish | Every action visible in the log |
| 12 | README, architecture diagram, demo recording | Video under 3 minutes on YouTube |
| 13 | Buffer, bug fixes, **submit early** | Devpost submission complete |

**If behind schedule, cut in this order:** F9 network → dashboard metrics → Transaction Search import (use the seed script data instead). **Never cut:** scoring with reasons, the graph, or the dispute copilot.

## 10. Demo video (under 3 minutes)

1. **0:00–0:20 Problem:** a small seller loses a sale and the stock to an "item not received" scam.
2. **0:20–0:50 A normal order** arrives live via webhook → low risk.
3. **0:50–1:30 The first-time scammer:** $480, freight forwarder, no Seller Protection → **high risk** with reasons.
4. **1:30–2:00 The graph:** click a buyer → 4 linked accounts sharing one address → the AI's one-line summary.
5. **2:00–2:40 A dispute arrives:** PayGuard shows the deadline and evidence, Claude drafts a response, the seller edits and clicks **Submit to PayPal**, and the status updates.
6. **2:40–3:00 The audit log, and the vision:** a shared network so one seller's scammer is flagged everywhere.

## 11. Submission checklist (from the hackathon rules)

- [ ] Public GitHub repo with all code, an **MIT LICENSE** visible in the About section, and setup instructions
- [ ] **Hosted demo URL** (Render) that judges can use without setup, with a demo login
- [ ] **YouTube video under 3 minutes**, public, showing it working; no copyrighted music
- [ ] Text description: problem, features, how PayPal and AI are used
- [ ] "Tools used" section: PayPal APIs, Claude models and what each does
- [ ] Clear note on anything simulated (e.g. dispute payloads, if the sandbox can't create them)

## 12. Risks and fallbacks

| Risk | Fallback |
|---|---|
| No sandbox access from Pakistan | Ask in the PayPal Discord (per the FAQ); team up with someone in a supported country |
| Sandbox can't create disputes | Record real dispute JSON shapes from the docs; run the copilot on them; label clearly |
| Transaction Search lag or permission issues | Use webhook and seed data for history |
| Render free tier sleeps (slow first load) | Warn in the README; keep the demo video as the primary proof |
| Time | Follow the cut order in section 9 |
