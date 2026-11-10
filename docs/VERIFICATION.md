# Ringside (code name PayGuard): Verification

What has been checked, how, and what the result was. Just as important, it lists what has **not** been checked yet. It's updated each build day.

---

## Day 1 (8 Nov): backend core

### Automated tests: `cd backend && .venv/bin/pytest`

**Result: 56 passed** (Python 3.14.3, Django 6.1.3, SQLite)

| File | Tests | What it proves |
|---|---|---|
| `test_rules.py` | 28 | Each rule fires and stays quiet at the right thresholds; exact reason text; 100 cap; sort order; level boundaries (29/30, 59/60); determinism |
| `test_normalize.py` | 5 | Address variants (`Street`/`st`, case, punctuation) share a key; numbered emails share a stem; hashes aren't plaintext; phone formatting is ignored |
| `test_webhooks.py` | 9 | Capture event → order + score + audit; **duplicate delivery processed once**; **forged signature → 400, never processed**; malformed → 400; GET → 405; **refund before order → 503, then 200 on retry**; stale dispute update can't overwrite newer state; unknown types acknowledged; velocity fires on the 3rd order to one address, not the 2nd |
| `test_demo_and_api.py` | 9 | All 60 normal orders score low; scammer is high with the expected rules; ring account 4 is linked to 3 accounts; ring account 3 was flagged before its dispute; injected buyer message is stored as data; **seed is deterministic** (same scores twice); API filter and detail; health endpoint |
| `test_sandbox_client.py` | 5 (mocked HTTP) | Credentials required; webhook verify sends the raw body **unchanged**; fails closed when headers are missing; FAILURE → false; OAuth token cached |

### Manual checks

| Check | Command | Result |
|---|---|---|
| Django system check | `manage.py check` | No issues |
| Full demo run | `manage.py seed_demo --reset --live` | 63 orders, 4 refunds, 1 dispute; live: normal **0/low**, scammer **90/high**, ring **70/high**, dispute **WAITING_FOR_SELLER_RESPONSE** |
| Score spread | Shell query | 63 low, 1 medium (ring account 3), 2 high, with **no false positives** on normal buyers |
| Live HTTP server | `runserver` + curl | `/api/health/` OK; `/api/orders/?level=high` returns exactly the scammer and ring account 4; `/api/disputes/` shows the deadline; forged webhook returns **400** |

### Demo outputs (copy for the README and video)

**Scammer, 90/100 high**
- +20 NOT_SELLER_PROTECTED: Order is not covered by PayPal Seller Protection
- +20 RESHIPPER_ADDRESS: Shipping address matches a known freight-forwarder / reshipper
- +15 COUNTRY_MISMATCH: Payer country CA, shipping country US
- +15 UNUSUAL_AMOUNT: USD 480.00 is 8.4x this shop's typical USD 57.30 order
- +10 DISPOSABLE_EMAIL: Email domain mailinator.com is a disposable-email service
- +10 UNVERIFIED_PAYER: Payer's PayPal account is not verified

**Ring account 4, 70/100 high**
- +35 LINKED_TO_BAD_ACTOR: Shares address / email pattern / phone with 3 accounts that refunded or disputed
- +20 NOT_SELLER_PROTECTED
- +15 COUNTRY_MISMATCH: Payer country GB, shipping country US

### Bugs found and fixed today

1. **Annotate after slice** in `risk/context.py`: Django can't annotate a sliced query. The annotation now runs before the slice.
2. **Linked accounts kept only their first link type**, so the reason said "address" when address, phone and email stem all matched. Every link type is now kept.
3. **Weak determinism test** that only compared counts. It now compares every payer's score and level across two seeded runs with a fixed timestamp.

### NOT verified yet ⚠️

| Item | Why | Plan |
|---|---|---|
| Sandbox client against real PayPal | No developer account | Run once credentials exist: OAuth, get_order, verify webhook |
| Exact PayPal payload fields in practice (e.g. whether `account_status` and `phone` are present) | Shapes taken from the docs | Compare against a real sandbox order; unknown fields degrade to "no finding" |
| PostgreSQL | Only SQLite run so far | Run the test suite against Postgres before deploying to Render |
| Performance at scale | Demo is ~65 orders | Fine for the demo; context queries are indexed on address, buyer and time |
| Real LLM output | No key | Template fallback is verified; LLM output will need its own guardrail tests |

---

## Day 2 (8 Nov): graph, dashboard, React UI, independent review

### Automated checks

| Check | Result |
|---|---|
| `cd backend && .venv/bin/pytest` | **91 passed** (71 before the review, plus 20 regression tests) |
| `cd frontend && npm run build` (TypeScript + Vite) | Passes. Main bundle 330 kB; the graph page is lazy-loaded (188 kB) |
| `npm run lint` (oxlint) | 0 errors, 2 warnings, both false positives (a custom hook's deps array, and fast-refresh in `main.tsx`) |

### Checked in a real browser (Chrome, macOS, dark mode)

| Page | What was confirmed |
|---|---|
| Overview | Money at risk $569.00 (2 orders), 1 open dispute (10 days left), 66 orders scored (2 high, 1 medium, 63 low), record 0–1; ring summary; riskiest buyers |
| Fraud rings | Only the real 4-account ring is detected. The graph lays out in rows (evidence → buyer → order → outcome); strong links are solid red; React Flow attribution is shown |
| Order detail (scammer) | Score bar 90, 6 findings with evidence, "Not protected" plus advice, forwarder tag |
| Unknown buyer `/rings?buyer=NOPE` | Shows "Not found: buyer not found." instead of a fake server-down error |
| Small graph → ring | The ring graph fits fully after switching (stale-zoom bug fixed) |

**Not checked:** phone-width layout (macOS refused to shrink the window to 400 px) and light mode. Check both before recording the video.

### Independent code review

Four reviewers (backend correctness, API contract, frontend UX, privacy/security) reported 26 issues. Three skeptics then tried to refute each one. **20 survived with 2 or 3 of 3 votes, 18 of them distinct. All 18 are fixed**; each backend one has a regression test in `backend/tests/test_review_fixes.py`.

| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | **High** | Raw PayPal JSON on orders, disputes and webhooks kept buyer emails and phones in plain text, contradicting "hashes only" | `redact()` strips emails and phones before storing; tested |
| 2 | **High** | `DEBUG` defaulted on with a public fallback secret key, and the debug page would show the hashing salt | On Render, DEBUG is off by default and startup **fails** without a real secret key and salt; secure cookies; 256 KB request limit; tested |
| 3 | Medium | Graph node IDs held hash prefixes that could be brute-forced back to phone numbers | Opaque node IDs (`phone:1`); hashing is now keyed HMAC-SHA256; tested |
| 4 | Medium | `?level=high` matched *any* past assessment, not the latest | Filters on the latest assessment; tested |
| 5 | Medium | Graph labelled every resolved dispute "lost", even wins | Backend sends `result` (won/lost); UI colours it; tested |
| 6 | Medium | Switching graphs kept the old zoom, cutting off the ring | Graph renders only data for the current URL; checked in the browser |
| 7 | Medium | Dark mode: zoom buttons turned white on hover, hiding their icons | CSS hover rule; checked in the browser |
| 8 | Low | A partial refund removed the whole order from money at risk | Counts the unrefunded remainder; tested |
| 9 | Low | Outcome `ACCEPTED` (seller paid) wasn't counted as a loss | Shared `core/outcomes.py` mapping; tested |
| 10 | Low | GBP and CAD amounts summed into "USD" | Totals use the seller's currency; others counted separately; tested |
| 11 | Low | Buyers with no email all "shared" one email pattern | Empty email → empty hash, skipped; tested |
| 12 | Low | Blank buyer names showed as empty cells | Fall back to payer ID; tested |
| 13 | Low | Route column flagged a mismatch when one side was blank | Only flags when both countries are known |
| 14 | Low | List pages silently cut off at the page limit | "Showing the newest N of M" note; explicit limits |
| 15 | Low | 404s showed "is the server running?" | Typed `ApiError`; 404 shows "Not found" |
| 16 | Low | A buyer's own (unshared) address was drawn as a red strong link | `shared` flag; unshared addresses drawn grey; tested |
| 17 | Low | Graph nodes couldn't be opened with the keyboard | Buyer and order nodes are focusable links (Enter/Space) |
| 18 | Low | Forged webhooks were stored in full, so anyone could flood the database | Unverified bodies are never stored; a forged event can't block the real one; tested |

**Rejected by the skeptics (not fixed):** cross-seller clustering (only one seller exists today); dashboard currency formatting (already correct); the "All high risk" link scope; unauthenticated API (a demo login is already planned for deploy day); forged mock-mode refunds (mock mode only); seller scoping (one seller).

### Still open

- **No login yet.** Every API endpoint is public. It must be added before deploying (planned for the deploy day).
- **The mock PayPal store (`MockPayPalObject`) still holds full PayPal payloads**, because it stands in for PayPal's own database. It's unused in sandbox mode.
- **Rate limiting on the webhook** is not done. Render's edge plus the 256 KB limit is the current protection.

---

## Day 3 (8 Nov, evening): dispute copilot, Gemini, git and MIT

### Automated checks

| Check | Result |
|---|---|
| `cd backend && .venv/bin/pytest` | **160 passed**: 91 from day 2, 34 copilot tests, 35 regression tests from the copilot review |
| `cd frontend && npm run build` / `npm run lint` | Build passes; 0 lint errors |
| Gemini paths | Tested with mocked HTTP: a valid draft is used; an injection-obeying draft, an invented tracking number, a 429 and a network error all **fall back to the template** with the reason recorded; caching; the key goes in a header, never the URL. **Not yet run against the real Gemini API (no key).** |

### Checked in a real browser (Chrome, dark mode, mock PayPal)

| Flow | Result |
|---|---|
| Disputes list | The open dispute shows "Ready: Fight"; the resolved one shows no Ready badge |
| Copilot page | Rules-based recommendation with evidence chips; editable draft; 5 evidence items; buyer message in a quarantined box |
| Approve and send | Inline confirm → "Sent to PayPal" → mock PayPal status **Under review**; the text PayPal received has no `[E#]` citations |
| Partial refund | The option is always offered, with the suggested $20.15 (30%) offer and a "buyer has to agree" note |
| Regenerate after changes | Asks "Replace my edits / Keep my edits" first |
| Resolved dispute | Read-only, with the PayPal status and outcome; risk and ring evidence labelled "internal · not sent to PayPal or AI" |

### Independent code review of the copilot commit

Five reviewers (guardrails, workflow correctness, evidence and rules, frontend, security and privacy) reported 34 issues, and three skeptics tried to refute each one. **23 were confirmed; all are fixed.** Each bypass the reviewers demonstrated is now a test in `backend/tests/test_copilot_review_fixes.py`.

**The safety check (guard) was rebuilt** rather than patched. Phrase lists leak, so the checks are now structural:

| # | Was possible | Now |
|---|---|---|
| 1 | "We'll refund the buyer the entire payment" passed in a Fight draft | Any refund, accept, reimburse or concede-style sentence is rejected unless it's copied word for word from the evidence |
| 2–3 | Invented numbers with `.`, `,` or `/`, any amount or date, or digits that happened to appear inside a real tracking number | Every number token must **exactly** match a number from the evidence; number words ("twelve") are rejected too |
| 4 | `[E1, E9]`, `(B1)` and other citation forms | Every E/B id in any form is checked; only `[E3]` is accepted, counted per occurrence |
| 5 | A partial-refund note promising a different amount, or a full refund | It must state the exact offer and no other amount |
| 6 | The ring summary inflating "USD 1,250.00" | The same number check is used for short AI texts |
| 23 | The internal risk score or ring links cited in text sent to PayPal | Risk and ring evidence is never given to the AI and can't be cited |
| 22 | Phone numbers and emails in buyer messages sent to Gemini | Masked before storage and before any AI call |

**Workflow and data:**

| # | Severity | Fix |
|---|---|---|
| 7 | High | Any error during the PayPal call (timeout, bad JSON) → FAILED, never stuck in SUBMITTING. A retry **checks PayPal first** and doesn't send twice |
| 8 | High | SUBMITTED is saved as soon as PayPal accepts; a failed status refresh is only logged |
| 13 | High | Buyer history and earlier lost disputes only count **this shop**; lost disputes are internal context, never sent |
| 14 | High | Seller Protection only counts as covering the claim if its categories include this dispute's reason |
| 18 | High | A failed send shows the FAILED state with the seller's text kept (it used to say "Bad Gateway" and silently re-draft) |
| 9 | Medium | Viewing a FAILED case no longer re-drafts it |
| 10 | Medium | Locking: a regenerate can't overwrite a submission in progress |
| 11 | Medium | A dispute with no known order → "needs data", prepared again when the order arrives |
| 15 | Medium | Buyer history counts only completed, delivered orders, worded exactly as checked |
| 16 | Medium | Evidence dates are in the seller's time zone (Juniper Lane: America/Chicago) |
| 19 | Medium | Disputes PayPal isn't waiting on are read-only |
| 20 | Medium | Regenerate asks before replacing edits; inputs lock while busy |
| 12, 17 | Low | Offers use the currency's minor unit (no decimals for JPY, HUF, TWD); the seller can set their own offer amount (validated) |
| 21 | Low | Native radio buttons; Escape cancels the confirm step; focus returns to the send button |

**Rejected by the skeptics:** narrow injection-echo regex (the structural checks cover it); carrier enum mapping; tracking without delivery recommending Fight (intended: send the tracking); several UI edge cases; audit storing draft text; emails or URLs in AI drafts; AI cache lifetime; GET with side effects.

### Still open

- **Real Gemini output is unverified**; it needs a key. The fallback guarantees the demo works without one.
- **Sandbox Disputes API calls are unverified**; they need credentials, expected tonight. The request shapes are unit-tested.
- **The safety check is a strong backstop, not a proof.** A model could still write misleading prose that uses only grounded numbers and no concession words. The seller's review and approval remain the final control, by design.
- **No login yet; the copilot GET prepares a case as a side effect.** Both are planned for the deploy day.

## Day 4 (9 Nov): VPS deploy

Checked against the live site, https://ringside.duckdns.org:

| Check | Result |
|---|---|
| `manage.py check --deploy` | 0 errors; 2 warnings (HSTS, SSL redirect), acceptable because Caddy serves this hostname on HTTPS only |
| `GET /api/health/` | 200 `{"ok": true, "paypal_mode": "mock", "ai_provider": "gemini"}` |
| `/`, SPA deep link `/disputes`, `/static/admin/css/base.css` | 200 |
| `GET /api/dashboard/` without login | 403 (auth enforced) |
| Login with CSRF token and `Origin` header, then dashboard, disputes, rings | 200 each; dashboard shows the 63 seeded orders |
| TLS | Let's Encrypt certificate, valid to 7 Feb 2027 |
| Other apps on the VPS | Caddy config validated before reload; containers and nginx untouched |

### Not verified yet

- Login and the pages in a real browser (only verified with curl).
- A Gemini call from the VPS (the key is set; the template fallback covers failures).
- PayPal webhooks to the live URL: `PAYPAL_WEBHOOK_ID` is empty and `PAYPAL_MODE` is `mock` on the server, as in local `.env`.

**Domain switch (9 Nov):** `ringside.duckdns.org` → 173.212.238.249; Let's Encrypt certificate for that name (valid to 7 Feb 2027); health, `/`, `/disputes`, login and dashboard return 200; the old sslip.io URL returns 301 to the same path on the new domain.

## Day 4b (9 Nov): real PayPal sandbox flow

### Automated checks
- Backend: **238 tests pass**, 62 of them new in `tests/test_sandbox_flow.py`. No test calls PayPal: a `no_network` fixture fails any HTTP call, and the conftest blanks the PayPal keys.
- `makemigrations --check`: no changes pending (new migration `core/0004_shipment_paypal_tracking_sent_at`).
- Frontend: `tsc -b` clean, `vite build` OK.
- Sandbox keys: an OAuth token comes back from `api-m.sandbox.paypal.com` (only OK or failed was printed).

### Independent review (4 reviewers, each finding checked by a separate verifier)

| Confirmed finding | Fix |
|---|---|
| After capture, a failed order lookup returned 202 with no order ID, so the bag emptied with no confirmation | 202 now carries `order_id` and `PENDING`, and the page shows a "processing, don't pay again" state |
| An order said COMPLETED while its capture was PENDING or DECLINED | The capture status is checked: DECLINED gives 402 with retry, PENDING gives 202 pending, and the paid state shows only for COMPLETED |
| An ingest crash after capture would return 500 to a buyer who had paid | Caught and recorded in the audit log; the buyer still gets the success response |
| The tracking `pattern` was invalid under the browser's `v` flag, and the placeholder had spaces the server rejected | Valid pattern; spaces stripped and uppercased on both client and server |
| Editing a shipment reset `shipped_at` and `delivered_at` to now, which changed dispute evidence | Existing dates are kept unless new ones are sent |
| A failed tracking push was never retried | `Shipment.paypal_tracking_sent_at`: an empty value means the next save resends |
| "Mark as shipped" re-drafted FAILED cases, which skipped the submit reconciliation | Only READY and NEEDS_DATA cases are re-drafted |
| Two events, or an event plus `--sync`, could prepare one case twice | `prepare()` returns early when another caller is preparing a fresh PREPARING case |
| A wrong `PAYPAL_MERCHANT_ID` relinked the shop; correcting it created an empty second shop | `connect_paypal --discover` stops on a mismatch, and relinking falls back to the single Juniper Lane seller |
| A concurrent first contact could hit IntegrityError on seller creation | Create inside a savepoint, falling back to get |
| Rate limits used a per-worker LocMemCache (3 gunicorn workers) | Production uses a shared FileBasedCache (`CACHE_DIR`, default `backend/.cache/`) |
| A VPS seeded by the old code has no simulator registrations | Deploy step: `seed_demo --reset` before switching to sandbox |
| Cancel in the shipment editor kept unsaved edits | Cancel resets the form |
| createOrder errors were hidden behind PayPal's generic message | The server's reason is shown |

**Rejected by the verifiers:**
- X-Forwarded-For spoofing: Caddy sets the header.
- Capture request-ID replay after a decline: unconfirmed, and declines are rare in the sandbox.
- Latin-1 webhook body: urllib3 2.x already sends UTF-8. Hardened anyway: the body is sent as bytes.
- `require-evidence` preconditions: PayPal's 422 is surfaced.
- Buttons clickable during capture.
- SQLite double scoring.

### Not verified yet
- **A real sandbox checkout, webhook delivery, tracking push and dispute.** These need the deploy, the webhook ID and the merchant ID on the VPS.
- **The shop page in a real browser.** The PayPal JS SDK renders only with sandbox mode on.

### Day 5 (10 Nov)
- `pytest tests/test_sandbox_flow.py tests/test_demo_and_api.py`: 72 passed (adds `demo_controls` in shop info, on and off).
- `tsc --noEmit` and `vite build` clean.
- Browser (local): shop strip renders, fraud-ring feed plays four lines in order, anonymous click shows the sign-in message. The signed-in path reuses the endpoint the sidebar menu already exercises; the "Open in Ringside" link is to check on the VPS after deploy.
