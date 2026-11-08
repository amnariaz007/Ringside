"""
Step 3b: check a draft before a seller ever sees it.

A draft that fails any check is thrown away and replaced by the template
draft, and the reasons are kept in the case's guard_notes for the audit log.

The checks are structural rather than a list of banned phrases:

  * Numbers: every number in the draft (amounts, dates, tracking numbers,
    however they are written) must exactly match a number in the shareable
    evidence. Number words ("twelve", "a thousand") are rejected unless the
    evidence uses them.
  * Concessions: in a FIGHT draft, any sentence with refund / accept /
    reimburse / concede-type wording is allowed only if it is copied from
    the evidence (e.g. "completed without a dispute or refund").
  * Citations: only the exact form [E3]; every id must exist and be
    shareable; buyer-message ids (B1) can never be cited.
  * Offers: a PARTIAL_REFUND draft must state the exact offer amount and no
    other amount.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

CITATION = re.compile(r"\[(E\d+)\]")
ANY_ID = re.compile(r"\b([EB])\s?(\d+)\b")
NUMBER = re.compile(r"\d[\d.,/:\- ]*\d|\d")
NUMBER_WORDS = re.compile(
    r"\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|forty|fifty|"
    r"hundred|thousand|million|dozen|several dozen)\b", re.IGNORECASE)
CONCESSION = re.compile(
    r"(refund|reimburs|money back|accept|concede|conced|not (contest|dispute)|won'?t (contest|dispute)|"
    r"don'?t (contest|dispute)|no longer (contest|dispute)|give up|in the buyer'?s favou?r|"
    r"return (the|their|your) (full|entire|whole)|full amount|entire (payment|amount)|"
    r"agree (with|to) the buyer)", re.IGNORECASE)
INJECTION_ECHO = re.compile(r"(ignore (all|your|the)? ?(previous|prior) instructions|as an ai\b|system prompt)",
                            re.IGNORECASE)
SENTENCE = re.compile(r"[^.!?]+[.!?]?")
MAX_CHARS = 2000   # PayPal's limit for evidence notes
MIN_CHARS = 60

# Evidence kinds that may go into text sent to PayPal. Risk scores and ring
# links are internal context: never given to the AI, never citable.
SHAREABLE = {"order", "seller_protection", "tracking", "delivery", "buyer_history"}


def shareable(evidence: list[dict]) -> list[dict]:
    return [e for e in evidence if e["kind"] in SHAREABLE]


# --- number handling ---------------------------------------------------------------

def _forms(token: str) -> set[str]:
    """All the ways a number token can match: its digits, and its value if it's an amount."""
    token = token.strip(" -/:.,")
    forms = {re.sub(r"\D", "", token)}
    try:
        forms.add(str(Decimal(token.replace(",", "")).normalize()))
    except InvalidOperation:
        pass
    return {f for f in forms if f}


def number_tokens(text: str) -> list[str]:
    return [t.strip(" -/:.,") for t in NUMBER.findall(text) if t.strip(" -/:.,")]


def evidence_numbers(evidence: list[dict]) -> set[str]:
    known: set[str] = set()
    for e in evidence:
        for source in (e.get("detail", ""), *(str(v) for v in (e.get("data") or {}).values())):
            for t in number_tokens(source):
                known |= _forms(t)
                # Also each separate digit group, so "7 Nov 2026" grounds "7" and "2026".
                known |= {g for g in re.findall(r"\d+", t)}
    return known


def ungrounded_numbers(text: str, known: set[str]) -> list[str]:
    bad = []
    for t in number_tokens(text):
        forms = _forms(t)
        if forms & known:
            continue
        # A date like 10/11/2026 or 7 Nov 2026 is grounded if every group is.
        groups = re.findall(r"\d+", t)
        if len(groups) > 1 and all(g in known for g in groups) and not any(len(g) >= 5 for g in groups):
            continue
        bad.append(t)
    return bad


# --- the check ---------------------------------------------------------------------

def check(draft: str, action: str, evidence: list[dict], *, offer_amount: Decimal | None = None,
          currency: str = "") -> list[str]:
    """Returns a list of problems; empty means the draft may be shown to the seller."""
    problems: list[str] = []
    text = draft.strip()
    allowed = shareable(evidence)
    ids = {e["id"] for e in allowed}
    internal = {e["id"] for e in evidence} - ids

    if not (MIN_CHARS <= len(text) <= MAX_CHARS):
        problems.append(f"length {len(text)} outside {MIN_CHARS}-{MAX_CHARS} characters")

    # Citations: every E/B id anywhere in the text, in any bracket style.
    mentioned = {f"{k}{n}" for k, n in ANY_ID.findall(text)}
    proper = set(CITATION.findall(text))
    if any(m.startswith("B") for m in mentioned):
        problems.append("cites a buyer message as evidence")
    unknown = {m for m in mentioned if m.startswith("E")} - ids - internal
    if unknown:
        problems.append(f"cites evidence that doesn't exist: {', '.join(sorted(unknown))}")
    leaked = {m for m in mentioned if m in internal}
    if leaked:
        problems.append(f"cites internal risk context that must not go to PayPal: {', '.join(sorted(leaked))}")
    # Every E-id occurrence must be a proper [E3] citation (counted, not just the set of ids).
    if sum(1 for k, _ in ANY_ID.findall(text) if k == "E") != len(CITATION.findall(text)):
        problems.append("citations must use the single-id form [E3]")
    if action == "FIGHT" and not proper:
        problems.append("a FIGHT response must cite at least one evidence item")

    known = evidence_numbers(allowed)
    if offer_amount is not None:
        known |= _forms(str(offer_amount))
    prose = ANY_ID.sub(" ", text)  # citation labels like [E3] aren't numbers
    for t in ungrounded_numbers(prose, known):
        problems.append(f"contains a number not found in the evidence: {t}")
    evidence_text = " ".join(e["detail"] for e in allowed).lower()
    for w in {m.lower() for m in NUMBER_WORDS.findall(text)} - set(NUMBER_WORDS.findall(evidence_text)):
        problems.append(f"contains a number word not found in the evidence: {w}")

    if action == "FIGHT":
        details = [re.sub(r"\s+", " ", e["detail"].rstrip(".")).lower() for e in allowed]
        for sentence in SENTENCE.findall(CITATION.sub("", text)):
            s = re.sub(r"\s+", " ", sentence.strip().rstrip(".!?")).lower()
            if s and CONCESSION.search(s) and not any(s in d or d in s for d in details if d):
                problems.append(f"concedes or offers money although the decision is to fight: \"{sentence.strip()[:80]}\"")

    if action == "PARTIAL_REFUND":
        if offer_amount is None:
            problems.append("partial refund without an offer amount")
        else:
            offer_forms = _forms(str(offer_amount))
            amounts = [t for t in number_tokens(prose) if "." in t or "," in t]
            if not any(_forms(a) & offer_forms for a in amounts):
                problems.append(f"doesn't state the offer amount {currency} {offer_amount}")
            others = [a for a in amounts if not _forms(a) & offer_forms]
            if others:
                problems.append(f"mentions amounts other than the offer: {', '.join(others)}")
        if re.search(r"\b(full|entire|whole) (refund|amount|payment)\b|accept (the|this|your) (claim|dispute|case)",
                     text, re.IGNORECASE):
            problems.append("promises more than the partial offer")

    if INJECTION_ECHO.search(text):
        problems.append("echoes instruction-like text")
    return problems


def strip_citations(text: str) -> str:
    """Citations help the seller review; PayPal's agent gets clean prose."""
    text = re.sub(r"\s?[\[(]\s*[EB]\s?\d+(\s*,\s*[EB]\s?\d+)*\s*[\])]", "", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()
