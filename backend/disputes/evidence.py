"""
Step 1 of the copilot: collect evidence for a dispute from our own records.

Every item gets a short id (E1, E2...). The recommendation and the AI draft
may only state facts that come from these items, and must cite their ids.
Buyer messages are collected separately as untrusted text (B1, B2...): they
are shown to the seller, but they are never evidence and never instructions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import re
from zoneinfo import ZoneInfo

from django.utils import timezone

from core.models import Dispute, Order
from core.outcomes import BUYER_WON

PROTECTED = {"ELIGIBLE", "PARTIALLY_ELIGIBLE"}

# Which Seller Protection category covers which dispute reason.
REASON_CATEGORY = {
    "MERCHANDISE_OR_SERVICE_NOT_RECEIVED": "ITEM_NOT_RECEIVED",
    "UNAUTHORISED": "UNAUTHORIZED_TRANSACTION",
}

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_PHONE = re.compile(r"\+?\d[\d\s().-]{6,}\d")


def redact_text(text: str) -> str:
    """Mask contact details a buyer typed into a message before storing or sending it anywhere."""
    text = _EMAIL.sub("[email removed]", text)
    text = _URL.sub("[link removed]", text)
    return _PHONE.sub("[number removed]", text)


INTERNAL_KINDS = {"risk", "ring"}  # shown to the seller, never sent to the AI or PayPal


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


def _fmt_date(dt, tz) -> str:
    """Dates in the seller's time zone, so they match the carrier's tracking page."""
    return timezone.localtime(dt, tz).strftime("%-d %b %Y") if dt else ""


def gather(dispute: Dispute) -> tuple[list[dict], list[dict]]:
    """Returns (evidence, buyer_messages), both JSON-ready."""
    items: list[Item] = []

    def add(kind, title, detail, supports="", **data):
        items.append(Item(f"E{len(items) + 1}", kind, title, detail, data, supports))

    order: Order | None = dispute.order
    if order is None:
        return [], _buyer_messages(dispute)
    tz = ZoneInfo(order.seller.timezone or "UTC")

    add("order", "Order details",
        f"PayPal order {order.paypal_order_id} for {order.currency} {order.amount}, placed {_fmt_date(order.created_at, tz)}.",
        paypal_order_id=order.paypal_order_id, amount=str(order.amount), currency=order.currency,
        created_at=order.created_at.isoformat())

    capture = dispute.capture or order.captures.first()
    if capture:
        status = capture.seller_protection_status or "UNKNOWN"
        needed = REASON_CATEGORY.get(dispute.reason)
        # Covered only if PayPal's categories include this dispute's reason.
        covered = status in PROTECTED and bool(needed) and needed in (capture.seller_protection_categories or [])
        add("seller_protection", "PayPal Seller Protection",
            f"PayPal reported Seller Protection status {status} for capture {capture.paypal_capture_id}"
            + (f", covering {_join(_CATEGORY.get(c, c.replace('_', ' ').lower()) for c in capture.seller_protection_categories)} claims."
               if capture.seller_protection_categories else "."),
            supports="fight" if covered else "", status=status, covers_this_claim=covered,
            categories=capture.seller_protection_categories, capture_id=capture.paypal_capture_id)

    shipment = getattr(order, "shipment", None)
    if shipment:
        add("tracking", "Shipping and tracking",
            f"The order shipped on {_fmt_date(shipment.shipped_at, tz)} with {shipment.carrier}, tracking number {shipment.tracking_number}"
            + (", to the address on the PayPal transaction." if shipment.to_paypal_address
               else ", to an address that differs from the PayPal transaction."),
            supports="fight", carrier=shipment.carrier, tracking_number=shipment.tracking_number,
            shipped_at=shipment.shipped_at.isoformat(), to_paypal_address=shipment.to_paypal_address)
        if shipment.status == "DELIVERED" and shipment.delivered_at:
            add("delivery", "Delivery confirmation",
                f"{shipment.carrier} confirmed delivery on {_fmt_date(shipment.delivered_at, tz)}"
                + (" with a signature." if shipment.signature_confirmed else "."),
                supports="fight", delivered_at=shipment.delivered_at.isoformat(),
                signature=shipment.signature_confirmed)
    else:
        add("tracking", "Shipping and tracking", "No shipment or tracking number is recorded for this order.",
            supports="accept", shipped=False)

    # Buyer's history with THIS shop, before this dispute (CE 3.0-style). Only orders that
    # completed and were delivered count; the wording says exactly what was checked.
    past = (Order.objects.filter(buyer=order.buyer, seller=order.seller, created_at__lt=order.created_at,
                                 status="COMPLETED", shipment__status="DELIVERED")
            .prefetch_related("disputes", "captures__refunds"))
    undisputed = [o for o in past
                  if not o.disputes.exists()
                  and any(c.status == "COMPLETED" for c in o.captures.all())
                  and not any(c.refunds.exists() for c in o.captures.all())]
    if undisputed:
        n = len(undisputed)
        add("buyer_history", "Buyer history with this shop",
            f"This payer has {n} earlier delivered order{'' if n == 1 else 's'} from this shop with no dispute "
            "or refund so far.", supports="fight", undisputed_orders=n)

    # Disputes this payer won against THIS shop: context for the seller, never sent to PayPal.
    lost_before = (Dispute.objects.filter(order__buyer=order.buyer, order__seller=order.seller,
                                          outcome__in=BUYER_WON, created_at__lt=dispute.created_at)
                   .exclude(pk=dispute.pk).count())

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
    if lost_before:
        add("risk", "Earlier disputes with this shop",
            f"This payer won {lost_before} earlier dispute{'' if lost_before == 1 else 's'} against this shop.",
            prior_disputes_won=lost_before)

    out = [asdict(i) | {"internal": i.kind in INTERNAL_KINDS} for i in items]
    return out, _buyer_messages(dispute)


def _buyer_messages(dispute: Dispute) -> list[dict]:
    msgs = [m for m in (dispute.raw.get("messages") or []) if m.get("posted_by") == "BUYER"]
    return [{"id": f"B{i}", "posted_at": m.get("time_posted", ""),
             "content": redact_text(str(m.get("content", "")))[:2000], "untrusted": True}
            for i, m in enumerate(msgs, 1)]
