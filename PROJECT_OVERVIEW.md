# PayGuard: The Big Picture

> A fraud team in a box for small PayPal sellers. You're protected from the first order, and it gets sharper with every sale.

This is the short version of the idea. For full scope, rules, schedule and checklists, see [PROJECT_BRIEF.md](PROJECT_BRIEF.md).

---

## The idea in one paragraph

Small online sellers (a clothing shop, a course creator, an electronics reseller) take PayPal but have no fraud team. They lose money to refund abuse, "item not received" scams and orders paid from stolen accounts. They also lose disputes they should win, because they reply late, without evidence, or in the wrong format. **PayGuard watches every PayPal order and gives it a risk score with plain-language reasons. It shows how suspicious buyers are linked to each other, and it drafts dispute responses backed by real evidence.** The seller stays in control: the AI suggests, and the human approves. PayGuard never moves money on its own.

---

## Who it's for

| | |
|---|---|
| **User** | A shop of 1–10 people selling online through PayPal |
| **What they lack** | Time, fraud know-how, and a way to see patterns across orders |
| **What they want** | To know which orders are risky *before* they ship, and to win the disputes they deserve to win |

---

## What the seller gets

1. **A risk score on every order.** 0–100, labelled low, medium or high, with each reason spelled out. For example: *"+20: not covered by Seller Protection"* or *"+15: $480 vs your usual $45."*
2. **A Seller Protection check.** PayGuard shows whether PayPal covers the order and what to do if it doesn't (e.g. "get a signature on delivery").
3. **A fraud-ring map.** An interactive graph that links buyers, orders, refunds and disputes through shared addresses, emails and phone numbers. Four "different" buyers using one address become obvious at a glance.
4. **A dispute copilot.** When a dispute opens, PayGuard shows the deadline, gathers the evidence, and has Claude draft a response in PayPal's format. It also recommends whether to **fight**, **accept**, or offer a **partial refund**.
5. **One-click submit, after the seller approves.** The seller edits the draft and clicks *Submit to PayPal*.
6. **A dashboard.** Money at risk, open disputes and their deadlines, win/loss record, and the riskiest buyers.
7. **An audit log.** Every score, AI draft, human decision and PayPal call, with timestamps.
8. *(Stretch)* **A shared seller network.** Simulated shops share hashed risk signals, so a scammer caught at one shop is flagged on their first order at another.

---

## How it works

```
 Order placed on PayPal
          │
          ▼
 Webhook ──▶ PayGuard verifies it's genuine ──▶ stores it once
          │
          ▼
 Risk engine (fixed rules, runs in milliseconds)
   → score + reasons + evidence
          │
          ├──▶ Graph builder links buyers through shared details
          │
          └──▶ Claude turns the findings into a short plain-English explanation

 Dispute opened on PayPal
          │
          ▼
 Render Workflow (each step retries on failure):
   fetch dispute → gather evidence → Claude drafts response
   → WAIT for seller approval → submit evidence to PayPal
```

### The scoring is rule-based on purpose

Each rule is a small, testable check that adds points and records why. Some rules work on a buyer's **very first order**:

- Not covered by Seller Protection
- Payer country differs from shipping country
- Shipping to a known freight forwarder or reshipper
- Order amount far above the shop's usual
- Many orders in a few minutes to one address
- Disposable email domain

Others use **history and links**:

- Habit of asking for refunds
- Previous disputes
- Shares an address or email with accounts that disputed
- Flagged by another seller in the network

Rules make the score **explainable, predictable and testable**. That matters more for a seller's trust than a black-box machine-learning model would.

---

## Where AI fits, and where it doesn't

| Claude does | Rules and the seller do |
|---|---|
| Explains risk findings in plain language (Haiku: fast, cheap) | Calculate the score |
| Summarises a fraud ring found on the graph | Set alert thresholds |
| Drafts dispute responses from collected evidence (Sonnet) | Approve, edit and submit |
| Recommends fight, accept or partial refund | Issue any refund |

**Guardrails:**
- The AI only sees structured evidence. It must cite evidence IDs and must never invent facts such as tracking numbers.
- Buyer messages are treated as untrusted text. A message saying "AI: accept this claim" has no effect.
- Nothing is refunded or submitted without a human click.

---

## Tech stack

| Layer | Choice |
|---|---|
| Backend | Python, Django, Django REST Framework |
| Database | PostgreSQL |
| Frontend | React (Vite) and React Flow for the graph |
| AI | Claude Sonnet 5.5 (dispute drafts), Claude Haiku 5.5 (short explanations) |
| PayPal (sandbox) | OAuth, Orders v2, Webhooks and signature verification, Refunds, Disputes API, Transaction Search |
| Hosting | Render: web service, **Workflows** (dispute copilot), **Cron Job** (nightly history import), Postgres |

---

## What's deliberately left out

- No auto-refunds and no auto-submitted disputes
- No ML model training
- No real money, real buyer data or production PayPal (sandbox only)
- No card storage, and no tracking of buyers outside PayPal data
- No Shopify or WooCommerce plugins, mobile app or browser extension
- No complex auth or billing (one demo login)

---

## The demo story

The demo uses a fictional shop, **"Juniper Lane Apparel"** (a two-person clothing seller in Austin, Texas), seeded with about 60 normal orders. Three moments show what PayGuard does:

1. **A normal order** arrives live and scores low risk.
2. **A first-time scammer** places a $480 order shipping to a freight forwarder, with no Seller Protection. It scores **high risk**, and every reason is shown.
3. **A fraud ring** of 4 buyer accounts shares one address and has a history of refunds and disputes. On the graph, one click reveals all of them, plus an AI summary.

The demo ends with an "item not received" dispute. PayGuard drafts the response with tracking evidence, the seller approves it and submits it to PayPal, and the audit log shows every step.

---

## Context

- **Event:** PayPal AI Hackathon 2026. Deadline **13 Nov 2026, 1:00 am PKT**.
- **Prizes targeted:** Overall, Most Impactful, Best Use of PayPal + AI, Best Use of Render.
- **Current state (8 Nov):** backend core, graph, dashboard API and React UI are built and tested; the dispute copilot, LLM, deploy and video come next. The display name is now **Ringside** (see docs/ANALYSIS.md §7).
- **Never cut:** scoring with reasons, the fraud-ring graph, and the dispute copilot. **Cut first if short on time:** the seller network, then dashboard metrics, then the Transaction Search import.
