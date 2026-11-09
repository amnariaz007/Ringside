# PayGuard: Analysis

A running record of how the idea holds up, what decisions were made and why, and what threatens the result. It's updated at the end of each build day.

---

## 1. The situation (8 Nov 2026)

| Fact | Impact |
|---|---|
| Deadline: **13 Nov, 1:00 am PKT** (= 12 Nov, 20:00 UTC) | **5 working days**, not the 13 the brief planned for |
| No PayPal developer account yet | The PayPal layer must run without one: a **mock mode** that uses PayPal's real data formats |
| No Claude API key | AI text must run without one: a **template mode**, with a real LLM added later |
| Building from Pakistan | PayPal sandbox access may be blocked. This is the biggest outside risk |

**Decision:** build everything behind two switches, `PAYPAL_MODE` (mock/sandbox) and `AI_PROVIDER` (template/LLM). No missing account blocks progress, and moving to the real services changes settings, not code.

---

## 2. Is the idea strong enough to win?

### Strengths

1. **A clear user with a painful, money-losing problem.** Small sellers lose both the money and the stock in "item not received" scams. Judges understand that in seconds.
2. **PayPal-specific depth, not just a payment button.** It uses Seller Protection status, the Disputes API, webhooks with signature checks and the Refunds API. Most hackathon entries only call Orders, so this fits **Best Use of PayPal**.
3. **AI used responsibly.** Rules decide, AI explains and drafts, a human approves, and there's a visible defence against prompt injection. That's a mature story for **Best Use of PayPal + AI**.
4. **Explainable scores.** Every point has a named rule and evidence. Judges can see exactly why the scammer scored 90.
5. **A memorable "aha" moment.** The fraud-ring graph, plus this fact from the seeded data: *PayGuard flagged ring account #3 (score 35, medium) before it filed the dispute that cost the seller money.*

### Weaknesses, and how to answer them

| Weakness | Mitigation |
|---|---|
| "Rules aren't AI." | Frame it as a deliberate trust choice: deterministic scoring, with AI where language matters. Show the guardrail demo. |
| Mock mode could look fake | Data formats follow PayPal's docs exactly, and the same parser handles both. If sandbox access arrives, show one real sandbox sale in the video. Label anything simulated honestly; the rules require it. |
| PayPal already has fraud tools for merchants | Those target larger merchants and are opaque. PayGuard is for sellers with no fraud team: it explains in plain words and handles the dispute work. |
| Five days is tight | Strict cut list (section 5). The core story needs only scoring, the graph and the dispute copilot. |

### Competitive positioning in this hackathon

The brief notes that agent guardrails, escrow and group-savings ideas are crowded (Bursar, MergePay, Stood, Acquit, SarafuPay). **Seller-side fraud and dispute defence is a less crowded lane.** Before submitting, check the Devpost gallery for other fraud or dispute entries and sharpen the difference.

---

## 3. Mapping to the judging prizes

| Prize | What wins it | PayGuard evidence |
|---|---|---|
| Overall | A working, polished demo of a real problem | Live webhook → score → graph → dispute draft → submit |
| Most Impactful | A clear user, money saved, accessibility | "A fraud team in a box" for 1–10 person shops |
| Best Use of PayPal + AI | Deep API use plus responsible AI | Seller Protection, Disputes API, guardrails, human approval |
| Best Use of Render | Uses more than a web service | Render **Workflows** with per-step retries for the dispute copilot, a Cron Job, and Postgres |

---

## 4. Day 1 decisions (8 Nov)

| Decision | Why |
|---|---|
| Django + DRF + SQLite locally, Postgres via `DATABASE_URL` | Zero setup today; same code on Render |
| Rules are pure functions over plain dataclasses (`OrderFacts`, `RiskContext`) | Testable without a database; easy to explain to judges |
| Mock PayPal client backed by a DB table | The simulator and the server can be separate processes, and webhooks fetch objects back exactly as from the real API |
| Demo data generated as PayPal JSON and fed through the real ingest code | The demo exercises the production code path, not a shortcut |
| Buyer email and phone stored only as salted hashes | Privacy; the fraud-ring links still work through matching hashes |
| An "email stem" hash (`sana.m1@` ≈ `sanam4@`) | Catches numbered throwaway accounts: a real fraud-ring pattern |
| Linked accounts record *every* link type (address, phone, email pattern) | The reason reads "Shares address / email pattern / phone with 3 accounts…", which is far more convincing than "address" alone |
| Webhook returns 503 when an event arrives before what it depends on | PayPal redelivers non-2xx events, so out-of-order events heal themselves |
| Unknown Seller Protection status scores 0 | Don't penalise missing data; say so in the README |
| The demo dispute's buyer message contains a prompt-injection attempt | Sets up the guardrail demo for the dispute copilot |

---

## 5. Compressed plan (5 days)

| Day | Goal | Done when |
|---|---|---|
| **8 Nov (today)** | Backend core: models, mock PayPal, webhooks, risk engine, demo data, tests | ✅ 56 tests pass; the demo scores 0 / 90 / 70 |
| 9 Nov | Graph API + React dashboard (orders list, order detail with reasons) | Clicking an order shows its findings |
| 10 Nov | React Flow graph view + dispute copilot (evidence, draft, recommend, approve) | The ring appears as a graph; the dispute draft ignores the injected instruction |
| 11 Nov | Render deploy (web, Postgres, Workflow), audit log view; sandbox if access exists; LLM provider if a key exists | Public URL works with a demo login |
| 12 Nov | README, architecture diagram, video under 3 minutes, **submit by 18:00 PKT** | Devpost submitted with time to spare |

**Cut order:** F9 network → Transaction Search cron → dashboard metrics → LLM (keep templates).
**Never cut:** scores with reasons, the graph, the dispute copilot with human approval.

---

## 6. Open questions

- [ ] PayPal sandbox access from Pakistan: ask in the hackathon Discord now.
- [ ] Can sandbox disputes be created and answered via the API? This decides whether F5/F6 are live or recorded.
- [ ] Which LLM provider (Gemini free tier recommended)? Do hackathon AI credits exist?
- [ ] Have Render hackathon credits been claimed?

---

## 7. Day 2 update (8 Nov, evening): what the research changed

Two research runs finished today. The full strategy is in [COMPETITIVE_STRATEGY.md](COMPETITIVE_STRATEGY.md); the fact-checked rules research is summarised here.

### Verified facts (from the official Devpost page and rules, fetched 8 Nov)

| Fact | Consequence |
|---|---|
| Deadline **12 Nov, 12:00 PT** (= 13 Nov 01:00 PKT) | Plan unchanged; aim to submit by 12 Nov 20:00 PKT |
| No tracks. PayPal (sandbox) must be **central**, plus any AI tool | The mock client must become a real sandbox client if at all possible |
| Five equal criteria: Tech, **Design** ("complete, coherent product"), Impact, Innovation, Presentation | Today's dashboard polish counts directly |
| Submission needs a hosted demo or full setup steps, a public repo with a visible licence, the AI tools explained, and a public video under 3 minutes | Git, LICENSE, README and the video are mandatory work, not polish |
| Best Use of Render pays **credits only**; the $5k honourable mentions include Most Impactful and Best Use of PayPal + AI | Render effort capped at about 1.5 days |
| The sandbox can create, answer and settle disputes entirely through the API (`POST /v1/customer/disputes`, `require-evidence`, `adjudicate`) | A real dispute demo is possible once credentials exist |
| The Agent Toolkit and MCP server only **list, get and accept** disputes, with no evidence submission | If used, it's Toolkit for reading and REST for the approved write |
| Render Workflows can't pause for human approval | Drafting is one run; approval starts a second run |
| Pakistan isn't on the excluded-countries list; sandbox account eligibility from Pakistan is **unconfirmed** | Still the biggest outside risk |

### Strategy findings (simulated judge panel; treat as informed opinion, not fact)

- **Dispute copilots are crowded** (about 40 public repos). Lead with **catching the ring before shipping**, with the copilot as the safety net.
- **The thin lanes** are a ring graph over one seller's own buyers, and hashed signals shared across sellers. No competitor was found doing either.
- **Judges' scores as planned:** 4 to 6 out of 10. The main deductions are mock-only PayPal and no LLM.

### Decisions made today

| Decision | Why |
|---|---|
| Demo shop changed from "Lahore Threads" to **Juniper Lane Apparel** (Austin, Texas) | PayPal doesn't support Pakistani merchants; a PayPal judge would notice |
| Display name changed to **Ringside** (code still uses `payguard`) | 25+ repos are called PayGuard, including one with the same idea. No "Ringside" fraud products or repos were found |
| An email pattern alone never links accounts; only **address and phone** are strong links | Same-name honest customers share email stems. Found by checking the seed data, now covered by a test |
| React Flow attribution kept visible | Hiding it requires a Pro subscription |

### Updated must-do list (from the strategy, adjusted)

1. **Today/tomorrow:** git, MIT LICENSE, public repo. Ask in the PayPal Discord about sandbox access from Pakistan (**the go/no-go is the end of 9 Nov**).
2. **9 Nov:** LLM provider (Gemini free tier, with the template as fallback) and the dispute copilot with an approval gate and the injection test.
3. **10 Nov:** Render Workflow, deployment, and real sandbox calls if access exists.
4. **11 Nov:** the two-seller network (the clearest innovation), the ring-replay hook, README.
5. **12 Nov:** video and submission.

---

## 8. Day 3 decisions (8 Nov, night)

| Decision | Why |
|---|---|
| **No Render.** Deploy to a VPS with Docker | Render is optional; its prize is credits only. The rule is a hosted demo or full setup steps, and a VPS satisfies it. The Render Workflow plan is dropped; the copilot keeps its step functions and runs inline |
| **Sponsor target: AG Grid** | Only AG Grid, APIMatic, Bryntum and Channel3 pay cash; one sponsor prize per project. AG Grid's is the largest ($5k / $2k / 3 × $1k) and fits a data-heavy seller tool. Orders, Disputes and the Audit log are now AG Grid (Community, MIT): custom risk-ring cells, reason chips, quick search, filters, pagination, CSV export. **Tick AG Grid on the Devpost form** |
| **"Ledger" visual identity** | Judges score Design ("a complete, coherent product"), and most entries look like dark AI dashboards. Warm paper, navy, serif headlines, tabular figures, and the logo's ring reused as the risk-score gauge |
| **One demo seller login** | Session login with CSRF protection and a per-IP attempt limit; every API endpoint needs it except health and the signed PayPal webhook. The credentials live in `.env` (git-ignored) and go in the Devpost text |
| **Production guard for any host** | `DJANGO_ENV=production` refuses to start with debug on or with development secrets |

**Prize plan now:** one main prize or honourable mention (Overall, Most Impactful, Most Creative, or Best Use of PayPal + AI), plus **AG Grid** as the sponsor prize.

## 9. Day 4 decisions (9 Nov): VPS deploy

| Decision | Why |
|---|---|
| **Deploy to the existing Contabo VPS** (`vmi3097504`, 173.212.238.249) | 4 vCPU, 7.8 GiB RAM (4.7 GiB free), 120 GB disk free, load ≈ 0.4. Plenty for one Django app plus a static build. It already hosts four other apps, so PayGuard is added beside them and nothing they use is changed |
| **systemd + gunicorn, not Docker** | The project has no Dockerfiles, and a venv and one unit file are faster to ship and debug before the deadline. Docker remains an option later |
| **Caddy for TLS; nginx left alone** | Caddy already owns :443 and issues certificates via TLS-ALPN; nginx owns :80 for another app. One Caddy site block serves the React build and proxies `/api` and `/admin` |
| **Hostname `ringside.duckdns.org`** | First deployed on `payguard.173-212-238-249.sslip.io`, which put the server IP in the URL. Moved to a DuckDNS name the same day (DuckDNS already serves the other apps here). The old address 301-redirects to the new one |
| **SQLite on the VPS** | A single host and demo-scale traffic; the file lives in `/opt/payguard/data/`. Postgres only if it is ever needed |

**Risk:** plain `http://` on this hostname reaches nginx's default site (another app), not PayGuard. Always share the `https://` link.

## 10. Day 4b decisions (9 Nov): real sandbox flow

| Decision | Why |
|---|---|
| **A public Juniper Lane storefront inside the same app (`/shop`)** | A real sandbox buyer needs somewhere to pay. One build and one domain keep it simple. It is clearly marked as a sandbox store, and the buyer never sees risk data |
| **Prices and totals computed on the server** | A buyer can't change the price by editing the request. Orders are created and captured with our keys, not by the browser SDK |
| **Keep the seeded history next to real orders (`RoutingClient`)** | The ring, risk history and dashboard need 30 days of data that one evening of sandbox testing can't produce. Each record goes to the PayPal it came from. The simulated history is labelled honestly in the README and video |
| **"Mark as shipped" sends tracking to PayPal** | Tracking is the core evidence for item-not-received disputes and a condition of Seller Protection. Sending it to PayPal shows deeper PayPal use |
| **Sandbox-only dispute controls exposed as a command, not in the UI** | They exist only in the sandbox. Keeping them out of the seller UI avoids suggesting a seller can make PayPal rule |
