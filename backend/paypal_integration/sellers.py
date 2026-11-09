"""
Which PayPal merchant the demo shop is.

Juniper Lane Apparel starts life with a placeholder merchant ID. Once the shop
is connected to a real PayPal sandbox business account (PAYPAL_MERCHANT_ID),
the same seller row takes that account's ID, so real sandbox orders land in
the same shop as the seeded history and the fraud ring.
"""

from __future__ import annotations

from django.conf import settings
from django.db import IntegrityError, transaction

from audit.models import record
from core.models import Seller

DEMO_MERCHANT_ID = "JUNIPERLANE01"
SHOP = {"name": "Juniper Lane Apparel", "currency": "USD", "timezone": "America/Chicago"}


def merchant_id() -> str:
    """The merchant ID the shop uses now: the real sandbox account if configured."""
    return settings.PAYPAL_MERCHANT_ID or DEMO_MERCHANT_ID


@transaction.atomic
def get_or_create_seller() -> Seller:
    mid = merchant_id()
    seller = Seller.objects.select_for_update().filter(paypal_merchant_id=mid).first()
    if seller:
        return seller
    if mid != DEMO_MERCHANT_ID:
        # The demo shop: the placeholder, or (if PAYPAL_MERCHANT_ID was corrected
        # after a wrong first link) the only Juniper Lane seller there is.
        shop = Seller.objects.select_for_update().filter(paypal_merchant_id=DEMO_MERCHANT_ID).first()
        if shop is None:
            same_name = list(Seller.objects.select_for_update().filter(name=SHOP["name"])[:2])
            shop = same_name[0] if len(same_name) == 1 else None
        if shop:
            previous = shop.paypal_merchant_id
            shop.paypal_merchant_id = mid
            shop.save(update_fields=["paypal_merchant_id"])
            record("system", "seller.linked_to_paypal", obj=shop, paypal_id=mid, previous_merchant_id=previous)
            return shop
    try:
        with transaction.atomic():
            return Seller.objects.create(paypal_merchant_id=mid, **SHOP)
    except IntegrityError:  # another request created it first
        return Seller.objects.get(paypal_merchant_id=mid)


def seller_for(merchant: str) -> Seller | None:
    """The seller a PayPal payload belongs to, linking the demo shop on first contact."""
    seller = Seller.objects.filter(paypal_merchant_id=merchant).first()
    if seller is None and merchant and merchant == settings.PAYPAL_MERCHANT_ID:
        seller = get_or_create_seller()
    return seller
