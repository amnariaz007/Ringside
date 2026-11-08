"""
AI text generation behind one interface.

AI_PROVIDER=template (the default) builds text from the rule findings with
plain code: free, instant, and it can never invent a fact. Real LLM providers
(Gemini, Groq, Claude) will implement the same methods and fall back to the
template on any error or rate limit, so the demo never breaks.

Guardrail for every provider: the input is structured findings only. Buyer
free text never reaches a prompt as instructions.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, Sequence

from django.conf import settings

from risk.rules import OrderFacts, RuleHit


@dataclass(frozen=True)
class AIText:
    text: str
    source: str  # which provider actually produced the text


class AIProvider(Protocol):
    name: str

    def explain_risk(self, *, score: int, level: str, hits: Sequence[RuleHit], facts: OrderFacts) -> AIText: ...
    def summarize_ring(self, stats: dict) -> AIText: ...


class TemplateProvider:
    name = "template"

    def explain_risk(self, *, score: int, level: str, hits: Sequence[RuleHit], facts: OrderFacts) -> AIText:
        if not hits:
            return AIText(f"Low risk ({score}/100): no warning signs found on this order.", self.name)

        top = hits[:3]
        reasons = "; ".join(f"{h.reason.rstrip('.')} (+{h.points})" for h in top)
        extra = f"; plus {len(hits) - 3} more signal(s)" if len(hits) > 3 else ""
        advice = {
            "high": "Hold shipment and review before fulfilling.",
            "medium": "Check the details before shipping; consider signature on delivery.",
            "low": "Safe to ship as normal.",
        }[level]
        return AIText(f"{level.capitalize()} risk ({score}/100): {reasons}{extra}. {advice}", self.name)

    def summarize_ring(self, stats: dict) -> AIText:
        def plural(n, word):
            return f"{n} {word}" + ("" if n == 1 else "s")

        cur = stats.get("currency", "USD")
        shared = [plural(stats[k], label) for k, label in (
            ("shared_addresses", "shipping address"), ("shared_phones", "phone number"),
            ("shared_email_patterns", "email pattern")) if stats.get(k)]
        if stats.get("buyers", 0) <= 1:
            parts = ["Not linked to any other account by shipping address or phone"]
        else:
            parts = [f"{plural(stats['buyers'], 'account')} share {_join(shared) or 'identifiers'}"]
        history = []
        if stats.get("refunds"):
            history.append(f"{plural(stats['refunds'], 'refund')} ({cur} {stats['refunded_amount']})")
        if stats.get("disputes_lost"):
            history.append(f"{plural(stats['disputes_lost'], 'lost dispute')} ({cur} {stats['lost_amount']})")
        elif stats.get("disputes"):
            history.append(plural(stats["disputes"], "dispute"))
        if history:
            who = "together they caused" if stats.get("buyers", 0) > 1 else "history:"
            parts.append(f"{who} {_join(history)}")
        text = "; ".join(parts) + "."
        if Decimal(stats.get("open_high_risk_amount") or "0") > 0:
            group = " from this group" if stats.get("buyers", 0) > 1 else ""
            text += (f" {cur} {stats['open_high_risk_amount']} in high-risk orders{group}"
                     " is still unshipped or unresolved: review before fulfilling.")
        return AIText(text[0].upper() + text[1:], self.name)


def _join(items: list[str]) -> str:
    """['a'] -> 'a'; ['a', 'b', 'c'] -> 'a, b and c'; [] -> ''."""
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


_PROVIDERS = {"template": TemplateProvider}


def get_provider() -> AIProvider:
    cls = _PROVIDERS.get(settings.AI_PROVIDER)
    if cls is None:
        # Unknown or not-yet-implemented provider: degrade safely instead of crashing.
        return TemplateProvider()
    return cls()
