"""
Step 1 of the copilot: collect evidence for a dispute from our own records.

Every item gets a short id (E1, E2...). The recommendation and the AI draft
may only state facts that come from these items, and must cite their ids.
Buyer messages are collected separately as untrusted text (B1, B2...): they
are shown to the seller, but they are never evidence and never instructions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from core.models import Dispute, Order
from core.outcomes import BUYER_WON

PROTECTED = {"ELIGIBLE", "PARTIALLY_ELIGIBLE"}


@dataclass
class Item:
    id: str
    kind: str      # order, tracking, delivery, seller_protection, buyer_history, risk, ring
    title: str
    detail: str
    data: dict = field(default_factory=dict)
    supports: str = ""   # "fight", "accept" or "" (neutral)


_CATEGORY = {"ITEM_NOT_RECEIVED": "item-not-received", "UNAUTHORIZED_TRANSACTION": "unauthorised-payment"}


def _join(items) -> str:
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _fmt_date(dt) -> str:
    return dt.strftime("%-d %b %Y") if dt else ""


def gather(dispute: Dispute) -> tuple[list[dict], list[dict]]:
    """Returns (evidence, buyer_messages), both JSON-ready."""
    items: list[Item] = []

    def add(kind, title, detail, supports="", **data):
        items.append(Item(f"E{len(items) + 1}", kind, title, detail, data, supports))

    order: Order | None = dispute.order
    if order is None:
        return [], _buyer_messages(dispute)

    add("order", "Order details",
        f"PayPal order {order.paypal_order_id} for {order.currency} {order.amount}, placed {_fmt_date(order.created_at)}.",
        paypal_order_id=order.paypal_order_id, amount=str(order.amount), currency=order.currency,
        created_at=order.created_at.isoformat())

    capture = dispute.capture or order.captures.first()
    if capture:
        status = capture.seller_protection_status or "UNKNOWN"
        covered = status in PROTECTED
        add("seller_protection", "PayPal Seller Protection",
            f"PayPal reported Seller Protection status {status} for capture {capture.paypal_capture_id}"
            + (f", covering {_join(_CATEGORY.get(c, c.replace('_', ' ').lower()) for c in capture.seller_protection_categories)} claims."
               if capture.seller_protection_categories else "."),
            supports="fight" if covered else "", status=status,
            categories=capture.seller_protection_categories, capture_id=capture.paypal_capture_id)

    shipment = getattr(order, "shipment", None)
    if shipment:
        add("tracking", "Shipping and tracking",
            f"The order shipped on {_fmt_date(shipment.shipped_at)} with {shipment.carrier}, tracking number {shipment.tracking_number}"
            + (", to the address on the PayPal transaction." if shipment.to_paypal_address
               else ", to an address that differs from the PayPal transaction."),
            supports="fight", carrier=shipment.carrier, tracking_number=shipment.tracking_number,
            shipped_at=shipment.shipped_at.isoformat(), to_paypal_address=shipment.to_paypal_address)
        if shipment.status == "DELIVERED" and shipment.delivered_at:
            add("delivery", "Delivery confirmation",
                f"{shipment.carrier} confirmed delivery on {_fmt_date(shipment.delivered_at)}"
                + (" with a signature." if shipment.signature_confirmed else "."),
                supports="fight", delivered_at=shipment.delivered_at.isoformat(),
                signature=shipment.signature_confirmed)
    else:
        add("tracking", "Shipping and tracking", "No shipment or tracking number is recorded for this order.",
            supports="accept", shipped=False)

    # Buyer's history with this shop, before this dispute (CE 3.0-style: past undisputed orders).
    past = (Order.objects.filter(buyer=order.buyer, seller=order.seller, created_at__lt=order.created_at)
            .prefetch_related("disputes", "captures__refunds"))
    undisputed = [o for o in past if not o.disputes.exists() and not any(c.refunds.exists() for c in o.captures.all())]
    lost_before = Dispute.objects.filter(order__buyer=order.buyer, outcome__in=BUYER_WON).exclude(pk=dispute.pk).count()
    if undisputed or lost_before:
        parts = []
        if undisputed:
            n = len(undisputed)
            parts.append(f"{n} earlier order{'' if n == 1 else 's'} from this payer completed without a dispute or refund")
        if lost_before:
            parts.append(f"this payer has won {lost_before} earlier dispute{'' if lost_before == 1 else 's'}")
        add("buyer_history", "Buyer history with this shop", "; ".join(parts).capitalize() + ".",
            supports="fight" if undisputed else "", undisputed_orders=len(undisputed), prior_disputes_won=lost_before)

    assessment = order.assessments.order_by("-created_at").first()
    if assessment and assessment.level != "low":
        add("risk", "Ringside risk score at checkout",
            f"Scored {assessment.score}/100 ({assessment.level}) when the order arrived: "
            + "; ".join(f.reason for f in assessment.findings.all()[:3]) + ".",
            score=assessment.score, level=assessment.level,
            rules=[f.rule for f in assessment.findings.all()])
        linked = assessment.findings.filter(rule="LINKED_TO_BAD_ACTOR").first()
        if linked:
            add("ring", "Linked accounts", linked.reason + ".", **linked.evidence)

    return [asdict(i) for i in items], _buyer_messages(dispute)


def _buyer_messages(dispute: Dispute) -> list[dict]:
    msgs = [m for m in (dispute.raw.get("messages") or []) if m.get("posted_by") == "BUYER"]
    return [{"id": f"B{i}", "posted_at": m.get("time_posted", ""), "content": str(m.get("content", ""))[:2000],
             "untrusted": True} for i, m in enumerate(msgs, 1)]
