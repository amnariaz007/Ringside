"""
AI text generation behind one interface.

AI_PROVIDER=template (the default) builds text from the rule findings with
plain code: free, instant, and it can never invent a fact.

AI_PROVIDER=gemini (with GEMINI_API_KEY) uses Google's Gemini through
ai/gemini.py. Every Gemini answer passes a safety check first, and any error,
rate limit or failed check falls back to the template, so the demo never breaks.

Guardrails for every provider:
  * Inputs are structured findings and evidence. AI never decides a score or
    an action; rules do.
  * Buyer messages are passed only as clearly fenced, untrusted data.
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
    cited: tuple[str, ...] = ()       # evidence ids cited (dispute drafts)
    notes: tuple[str, ...] = ()       # why an AI answer was rejected, if it was


class AIProvider(Protocol):
    name: str

    def explain_risk(self, *, score: int, level: str, hits: Sequence[RuleHit], facts: OrderFacts) -> AIText: ...
    def summarize_ring(self, stats: dict) -> AIText: ...
    def draft_dispute(self, *, action: str, reason: str, evidence: list[dict], buyer_messages: list[dict],
                      offer_amount: Decimal | None, currency: str) -> AIText: ...


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


    def draft_dispute(self, *, action: str, reason: str, evidence: list[dict], buyer_messages: list[dict],
                      offer_amount: Decimal | None, currency: str) -> AIText:
        """Assembles evidence sentences verbatim, each with its citation. Can't invent a fact."""
        from disputes.guard import shareable
        by_kind = {e["kind"]: e for e in shareable(evidence)}
        order = by_kind.get("order")
        order_ref = f"PayPal order {order['data']['paypal_order_id']}" if order else "this order"
        claim = REASON_LABELS.get(reason, reason.replace("_", " ").lower())
        lines: list[str] = []
        cited: list[str] = []

        def use(kind: str) -> None:
            e = by_kind.get(kind)
            if e:
                # Citation goes inside the sentence: "...delivered on 10 Nov [E4]."
                lines.append(f"{e['detail'].rstrip('.')} [{e['id']}].")
                cited.append(e["id"])

        if action == "FIGHT":
            lines.append(f"Hello, we're responding to the {claim} claim on {order_ref}.")
            for kind in ("tracking", "delivery", "seller_protection", "buyer_history"):
                # Only evidence that actually supports the defence goes into a FIGHT response.
                if kind == "tracking" or by_kind.get(kind, {}).get("supports") == "fight":
                    use(kind)
            lines.append("Based on this shipping and delivery record, we ask PayPal to close the case in the "
                         "seller's favour. Thank you for reviewing it.")
        elif action == "PARTIAL_REFUND":
            amount = f"{currency} {offer_amount}" if offer_amount is not None else "a partial refund"
            ref = f" [{order['id']}]" if order else ""
            lines.append(f"Hello, we're sorry the item on {order_ref}{ref} didn't meet expectations.")
            if order:
                cited.append(order["id"])
            lines.append(f"To settle this quickly, we'd like to offer a partial refund of {amount}, "
                         "and the buyer can keep the item.")
        else:
            lines.append(f"Hello, we've reviewed the {claim} claim on {order_ref}.")
            use("order")
            lines.append("We accept the claim and are sorry for the trouble.")
        return AIText(" ".join(lines), self.name, tuple(cited))


REASON_LABELS = {
    "MERCHANDISE_OR_SERVICE_NOT_RECEIVED": "item not received",
    "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED": "item not as described",
    "UNAUTHORISED": "unauthorised payment",
}


def _join(items: list[str]) -> str:
    """['a'] -> 'a'; ['a', 'b', 'c'] -> 'a, b and c'; [] -> ''."""
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def get_provider() -> AIProvider:
    if settings.AI_PROVIDER == "gemini" and settings.GEMINI_API_KEY:
        from .gemini import GeminiProvider, WithFallback
        return WithFallback(GeminiProvider(), TemplateProvider())
    # template, an unknown provider, or gemini without a key: degrade safely instead of crashing.
    return TemplateProvider()
