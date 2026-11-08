"""Build OrderFacts and RiskContext for an order from the database."""

from __future__ import annotations

from datetime import timedelta
from statistics import median

from django.db.models import Count, Q

from core.models import Buyer, Dispute, Order, Refund

from . import rules
from .lists import DISPOSABLE_EMAIL_DOMAINS


def order_facts(order: Order) -> rules.OrderFacts:
    capture = order.captures.order_by("captured_at").first()
    addr = order.shipping_address
    return rules.OrderFacts(
        order_id=order.paypal_order_id,
        amount=order.amount,
        currency=order.currency,
        created_at=order.created_at,
        payer_country=order.payer_country,
        ship_country=addr.country_code if addr else "",
        seller_protection_status=capture.seller_protection_status if capture else "",
        email_domain=order.buyer.email_domain,
        payer_account_status=order.buyer.account_status,
        address_is_reshipper=bool(addr and addr.is_reshipper),
        address_text=str(addr) if addr else "",
    )


def _buyer_history(buyer: Buyer, before) -> tuple[int, int]:
    """(refunds, disputes) for a buyer, counting only events before `before`."""
    refunds = Refund.objects.filter(capture__order__buyer=buyer, created_at__lt=before).count()
    disputes = Dispute.objects.filter(order__buyer=buyer, created_at__lt=before).count()
    return refunds, disputes


def _linked_accounts(order: Order) -> tuple[rules.LinkedAccount, ...]:
    """Other buyers who share this order's address, phone or email pattern."""
    buyer = order.buyer
    links: dict[int, set[str]] = {}

    if order.shipping_address_id:
        for bid in (
            Order.objects.filter(shipping_address_id=order.shipping_address_id, created_at__lt=order.created_at)
            .exclude(buyer=buyer).values_list("buyer_id", flat=True).distinct()
        ):
            links.setdefault(bid, set()).add("address")
    if buyer.phone_hash:
        for bid in Buyer.objects.filter(phone_hash=buyer.phone_hash).exclude(pk=buyer.pk).values_list("pk", flat=True):
            links.setdefault(bid, set()).add("phone")
    if buyer.email_stem_hash:
        for bid in Buyer.objects.filter(email_stem_hash=buyer.email_stem_hash).exclude(pk=buyer.pk).values_list("pk", flat=True):
            links.setdefault(bid, set()).add("email_pattern")

    result = []
    for other in Buyer.objects.filter(pk__in=links):
        refunds, disputes = _buyer_history(other, order.created_at)
        result.append(rules.LinkedAccount(other.payer_id, tuple(sorted(links[other.pk])), refunds, disputes))
    return tuple(sorted(result, key=lambda a: a.payer_id))


def risk_context(order: Order) -> rules.RiskContext:
    at = order.created_at
    buyer = order.buyer

    # Shop baseline: this seller's orders before this one.
    past_amounts = list(
        Order.objects.filter(seller=order.seller, created_at__lt=at).values_list("amount", flat=True)
    )
    shop_median = median(past_amounts) if past_amounts else None

    # Velocity: orders to the same address in the window ending at this order.
    orders_in_window = new_buyers_in_window = 1
    if order.shipping_address_id:
        window_start = at - timedelta(minutes=rules.VELOCITY_WINDOW_MINUTES)
        recent = Order.objects.filter(
            shipping_address_id=order.shipping_address_id, created_at__gte=window_start, created_at__lte=at
        ).select_related("buyer")
        orders_in_window = recent.count()
        new_buyers_in_window = (
            recent.filter(buyer__first_seen_at__gte=window_start).values("buyer").distinct().count()
        )

    # Buyer's own history.
    recent_orders = list(
        Order.objects.filter(buyer=buyer, created_at__lt=at)
        .annotate(n_refunds=Count("captures__refunds", filter=Q(captures__refunds__created_at__lt=at)))
        .order_by("-created_at")[: rules.REFUND_HABIT_LOOKBACK]
    )
    recent_refunds = sum(1 for o in recent_orders if o.n_refunds)
    disputes_in_window = Dispute.objects.filter(
        order__buyer=buyer,
        created_at__gte=at - timedelta(days=rules.PRIOR_DISPUTES_DAYS),
        created_at__lt=at,
    ).count()

    return rules.RiskContext(
        shop_median_amount=shop_median,
        shop_order_count=len(past_amounts),
        orders_to_address_in_window=orders_in_window,
        new_buyers_to_address_in_window=new_buyers_in_window,
        buyer_recent_order_count=len(recent_orders),
        buyer_recent_refund_count=recent_refunds,
        buyer_disputes_in_window=disputes_in_window,
        linked_accounts=_linked_accounts(order),
        disposable_domains=DISPOSABLE_EMAIL_DOMAINS,
    )
