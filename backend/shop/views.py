"""
The public Juniper Lane checkout. Buyers pay with a real PayPal sandbox account;
the paid order then reaches Ringside like any other PayPal order (it is scored
straight away here, and again idempotently when the capture webhook arrives).

Buyers never see risk scores: the responses only say whether the payment went through.
"""

from __future__ import annotations

import json
import re

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from audit.models import record
from core.auth_views import _client_ip
from paypal_integration.client import PayPalError, get_client
from paypal_integration.ingest import MissingDependency
from paypal_integration.sellers import SHOP
from webhooks.service import ingest_and_score

from .catalog import CURRENCY, CartError, build_purchase_unit, public_products

ORDER_ID = re.compile(r"^[A-Z0-9]{10,30}$")
LIMITS = {"create": 20, "capture": 20}  # per IP per window
WINDOW_SECONDS = 10 * 60


def _checkout_enabled() -> bool:
    return settings.PAYPAL_MODE == "sandbox" and bool(settings.PAYPAL_CLIENT_ID and settings.PAYPAL_CLIENT_SECRET)


def _limited(request, kind: str) -> bool:
    key = f"shop-{kind}:{_client_ip(request)}"
    count = cache.get(key, 0)
    if count >= LIMITS[kind]:
        return True
    cache.set(key, count + 1, WINDOW_SECONDS)
    return False


@require_GET
@ensure_csrf_cookie
def shop_info(request):
    enabled = _checkout_enabled()
    return JsonResponse({
        "shop": {"name": SHOP["name"], "location": "Austin, Texas"},
        "currency": CURRENCY,
        "products": public_products(),
        "checkout_enabled": enabled,
        # The client ID is public by design: PayPal's JS SDK puts it in the page's script URL.
        "paypal_client_id": settings.PAYPAL_CLIENT_ID if enabled else "",
    })


@require_POST
@csrf_protect
def create_order(request):
    if not _checkout_enabled():
        return JsonResponse({"detail": "Checkout runs only in PayPal sandbox mode."}, status=409)
    if _limited(request, "create"):
        return JsonResponse({"detail": "Too many checkouts. Try again in a few minutes."}, status=429)
    try:
        body = json.loads(request.body or b"{}")
        unit = build_purchase_unit(body.get("items") if isinstance(body, dict) else None)
    except ValueError as exc:  # includes CartError and bad JSON
        message = str(exc) if isinstance(exc, CartError) else "Malformed request."
        return JsonResponse({"detail": message}, status=400)
    try:
        order = get_client().create_order(unit)
    except PayPalError as exc:
        record("system", "shop.create_failed", error=str(exc)[:300])
        return JsonResponse({"detail": "PayPal could not start the checkout. Please try again."}, status=502)
    record("system", "shop.order_created", paypal_id=order.get("id", ""), amount=unit["amount"]["value"])
    return JsonResponse({"id": order["id"]})


@require_POST
@csrf_protect
def capture_order(request, order_id: str):
    if not _checkout_enabled():
        return JsonResponse({"detail": "Checkout runs only in PayPal sandbox mode."}, status=409)
    if not ORDER_ID.match(order_id):
        return JsonResponse({"detail": "Unknown order."}, status=404)
    if _limited(request, "capture"):
        return JsonResponse({"detail": "Too many attempts. Try again in a few minutes."}, status=429)
    client = get_client()
    try:
        client.capture_order(order_id)
    except PayPalError as exc:
        # A retried capture (double click, network blip) fails with ORDER_ALREADY_CAPTURED;
        # the order itself tells us whether the money actually moved.
        captured_already = "ORDER_ALREADY_CAPTURED" in str(exc)
        if not captured_already:
            record("system", "shop.capture_failed", paypal_id=order_id, error=str(exc)[:300])
            declined = "INSTRUMENT_DECLINED" in str(exc)
            return JsonResponse({"detail": "The payment was declined. Please choose another way to pay."
                                 if declined else "PayPal could not complete the payment.",
                                 "retry": declined}, status=402 if declined else 502)
    try:
        order_json = client.get_order(order_id)
    except PayPalError as exc:
        record("system", "shop.capture_lookup_failed", paypal_id=order_id, error=str(exc)[:300])
        return JsonResponse({"status": "PENDING", "order_id": order_id,
                             "detail": "Payment sent to PayPal. Your confirmation will follow by email."}, status=202)

    # The order can say COMPLETED while its capture is still PENDING (e.g. the
    # seller account must accept the payment) or was DECLINED: trust the capture.
    captures = (order_json.get("purchase_units") or [{}])[0].get("payments", {}).get("captures") or [{}]
    capture_status = captures[0].get("status", "")
    if order_json.get("status") != "COMPLETED" or capture_status == "DECLINED":
        record("system", "shop.capture_failed", paypal_id=order_id, order_status=order_json.get("status", ""),
               capture_status=capture_status)
        return JsonResponse({"detail": "The payment was declined. Please choose another way to pay.", "retry": True},
                            status=402)

    record("paypal", "shop.payment_captured", paypal_id=order_id, capture_status=capture_status,
           reason=captures[0].get("status_details", {}).get("reason", ""),
           amount=order_json["purchase_units"][0]["amount"]["value"])
    try:
        ingest_and_score(order_json)
    except MissingDependency as exc:
        # Usually PAYPAL_MERCHANT_ID isn't set; the capture webhook will retry later.
        record("system", "shop.ingest_deferred", paypal_id=order_id, reason=str(exc)[:300])
    except Exception as exc:  # the money has moved: never answer the buyer with a 500
        record("system", "shop.ingest_failed", paypal_id=order_id, error=str(exc)[:300])
    if capture_status == "PENDING":
        return JsonResponse({"status": "PENDING", "order_id": order_id,
                             "detail": "PayPal is still processing this payment."}, status=202)
    return JsonResponse({"status": "COMPLETED", "order_id": order_id})
