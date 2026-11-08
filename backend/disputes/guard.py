"""
Step 3b: check an AI-written draft before a seller ever sees it.

A draft that fails any check is thrown away and replaced by the template
draft, and the reasons are kept in the case's guard_notes for the audit log.
"""

from __future__ import annotations

import re

CITATION = re.compile(r"\[(E\d+)\]")
LONG_NUMBER = re.compile(r"\d[\d -]{4,}\d")  # tracking numbers, phone numbers, order ids
MAX_CHARS = 2000   # PayPal's limit for evidence notes
MIN_CHARS = 60

# Phrases that would concede the case. A FIGHT draft must never contain them,
# whatever the buyer's message told the model to write.
CONCEDING = re.compile(
    r"\b(accept(ing)? (the|this|your) claim|full refund|refund (you|the buyer) in full|we will refund|"
    r"issue a refund|agree to refund|we accept)\b", re.IGNORECASE)
INJECTION_ECHO = re.compile(r"(ignore (all|your|the)? ?(previous|prior) instructions|as an ai|system prompt)", re.IGNORECASE)


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def check(draft: str, action: str, evidence: list[dict]) -> list[str]:
    """Returns a list of problems; empty means the draft may be shown to the seller."""
    problems: list[str] = []
    text = draft.strip()
    ids = {e["id"] for e in evidence}
    evidence_digits = " ".join(_digits(e["detail"]) + " " + _digits(str(e.get("data", ""))) for e in evidence)

    if not (MIN_CHARS <= len(text) <= MAX_CHARS):
        problems.append(f"length {len(text)} outside {MIN_CHARS}-{MAX_CHARS} characters")

    cited = set(CITATION.findall(text))
    unknown = cited - ids
    if unknown:
        problems.append(f"cites evidence that doesn't exist: {', '.join(sorted(unknown))}")
    if action == "FIGHT" and not cited:
        problems.append("a FIGHT response must cite at least one evidence item")
    if re.search(r"\[B\d+\]", text):
        problems.append("cites a buyer message as evidence")

    for number in LONG_NUMBER.findall(text):
        if _digits(number) not in evidence_digits:
            problems.append(f"contains a number not found in the evidence: {number.strip()}")

    if action == "FIGHT" and CONCEDING.search(text):
        problems.append("concedes the claim although the decision is to fight")
    if INJECTION_ECHO.search(text):
        problems.append("echoes instruction-like text")
    return problems


def strip_citations(text: str) -> str:
    """Citations help the seller review; PayPal's agent gets clean prose."""
    return re.sub(r"\s?\[(E\d+)\]", "", text).strip()
