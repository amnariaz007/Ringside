"""Numbers for the seller's home screen."""

from decimal import Decimal

from django.db.models import OuterRef, Subquery
from django.utils import timezone

from risk.models import RiskAssessment

from .models import Dispute, Order, Seller
from .outcomes import BUYER_WON, SELLER_WON

OPEN_DISPUTE_STATUSES = {"OPEN", "WAITING_FOR_SELLER_RESPONSE", "WAITING_FOR_BUYER_RESPONSE", "UNDER_REVIEW"}


def with_latest_assessment(qs):
    latest = RiskAssessment.objects.filter(order=OuterRef("pk")).order_by("-created_at")
    return qs.annotate(
        latest_score=Subquery(latest.values("score")[:1]),
        latest_level=Subquery(latest.values("level")[:1]),
    )


def refunded_total(order) -> Decimal:
    return sum((r.amount for c in order.captures.all() for r in c.refunds.all()), Decimal("0"))


def summary(now=None) -> dict:
    now = now or timezone.now()
    orders = list(
        with_latest_assessment(Order.objects.select_related("buyer", "seller"))
        .prefetch_related("captures__refunds", "disputes")
    )

    seller = Seller.objects.order_by("pk").first()
    currency = seller.currency if seller else "USD"

    level_counts = {"low": 0, "medium": 0, "high": 0}
    at_risk_orders, at_risk_amount, other_currency = [], Decimal("0"), 0
    for o in orders:
        if o.latest_level:
            level_counts[o.latest_level] += 1
        if o.latest_level not in {"medium", "high"} or o.disputes.all():
            continue
        unrefunded = o.amount - refunded_total(o)
        if unrefunded <= 0:
            continue
        if o.currency != currency:
            other_currency += 1  # never add GBP to USD
            continue
        at_risk_amount += unrefunded
        at_risk_orders.append(o)

    disputes = list(Dispute.objects.select_related("order__buyer"))
    open_disputes = [d for d in disputes if d.status in OPEN_DISPUTE_STATUSES]
    resolved = [d for d in disputes if d.outcome]

    buyers: dict[str, dict] = {}
    for o in orders:
        if o.latest_score is None:
            continue
        b = buyers.setdefault(o.buyer.payer_id, {
            "payer_id": o.buyer.payer_id, "name": str(o.buyer), "max_score": 0, "level": "low", "orders": 0,
        })
        b["orders"] += 1
        if o.latest_score > b["max_score"]:
            b["max_score"], b["level"] = o.latest_score, o.latest_level

    return {
        "orders_total": len(orders),
        "level_counts": level_counts,
        "money_at_risk": {
            "currency": currency,
            "risky_orders_amount": str(at_risk_amount),
            "risky_orders_count": len(at_risk_orders),
            "other_currency_orders": other_currency,
            "open_disputes_amount": str(sum((d.amount for d in open_disputes if d.currency == currency), Decimal("0"))),
        },
        "open_disputes": [
            {
                "id": d.pk, "paypal_dispute_id": d.paypal_dispute_id, "reason": d.reason, "status": d.status,
                "amount": str(d.amount), "currency": d.currency,
                "buyer": str(d.order.buyer) if d.order else "",
                "due_at": d.seller_response_due_at.isoformat() if d.seller_response_due_at else None,
                "hours_left": round((d.seller_response_due_at - now).total_seconds() / 3600, 1)
                if d.seller_response_due_at else None,
            }
            for d in sorted(open_disputes, key=lambda d: d.seller_response_due_at or now)
        ],
        "dispute_record": {
            "won": sum(1 for d in resolved if d.outcome in SELLER_WON),
            "lost": sum(1 for d in resolved if d.outcome in BUYER_WON),
            "other": sum(1 for d in resolved if d.outcome not in SELLER_WON | BUYER_WON),
        },
        "riskiest_buyers": sorted((b for b in buyers.values() if b["max_score"] > 0),
                                 key=lambda b: -b["max_score"])[:5],
        "recent_risky_orders": [
            {"id": o.pk, "paypal_order_id": o.paypal_order_id, "buyer": str(o.buyer),
             "amount": str(o.amount), "currency": o.currency, "score": o.latest_score, "level": o.latest_level,
             "created_at": o.created_at.isoformat()}
            for o in sorted(at_risk_orders, key=lambda o: o.created_at, reverse=True)[:5]
        ],
    }
