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
