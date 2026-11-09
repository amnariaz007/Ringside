"""
"Mark as shipped": the seller records carrier and tracking for an order.

Tracking is the main evidence for item-not-received disputes and a condition
of PayPal Seller Protection, so it is also sent to PayPal (Orders v2 "track").
If an open dispute is waiting on this order, its copilot is re-prepared so the
new evidence is used.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from audit.models import record
from paypal_integration.client import PayPalError, get_client

from .models import Order, Shipment

CARRIERS = {"USPS": "USPS", "UPS": "UPS", "FEDEX": "FedEx", "DHL": "DHL"}
TRACKING = re.compile(r"^[A-Za-z0-9-]{6,40}$")


class ShipmentError(ValueError):
    pass


def _parse_time(value, field: str) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise ShipmentError(f"{field} must be an ISO date or date-time") from exc
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    if parsed > timezone.now() + timedelta(minutes=5):
        raise ShipmentError(f"{field} can't be in the future")
    return parsed


def record_shipment(order: Order, data: dict) -> tuple[Shipment, str]:
    """Validate and save the shipment, then push tracking to PayPal. Returns (shipment, paypal_status)."""
    carrier = str(data.get("carrier", "")).upper()
    # Carriers print numbers with spaces ("9400 1000 ..."); PayPal wants them without.
    tracking = re.sub(r"\s+", "", str(data.get("tracking_number", ""))).upper()
    if carrier not in CARRIERS:
        raise ShipmentError(f"carrier must be one of {', '.join(CARRIERS)}")
    if not TRACKING.match(tracking):
        raise ShipmentError("tracking number must be 6-40 letters, digits or dashes")
    capture = order.captures.filter(status="COMPLETED").order_by("captured_at").first()
    if capture is None:
        raise ShipmentError("this order has no completed payment to ship against")

    requested_ship = _parse_time(data.get("shipped_at"), "shipped_at")
    requested_delivery = _parse_time(data.get("delivered_at"), "delivered_at")
    delivered = bool(data.get("delivered"))

    with transaction.atomic():
        previous = Shipment.objects.select_for_update().filter(order=order).first()
        # Editing a shipment keeps its real dates unless new ones are given: they are dispute evidence.
        shipped_at = requested_ship or (previous.shipped_at if previous else timezone.now())
        delivered_at = None
        if delivered:
            kept = previous.delivered_at if previous and previous.status == "DELIVERED" else None
            delivered_at = requested_delivery or kept or timezone.now()
        if shipped_at < order.created_at:
            raise ShipmentError("shipping can't be before the order was placed")
        if delivered_at and delivered_at < shipped_at:
            raise ShipmentError("delivery can't be before shipping")
        tracking_changed = previous is None or (previous.carrier, previous.tracking_number) != (carrier, tracking)
        needs_push = tracking_changed or previous.paypal_tracking_sent_at is None
        shipment, _ = Shipment.objects.update_or_create(order=order, defaults={
            "carrier": carrier, "tracking_number": tracking,
            "status": "DELIVERED" if delivered else "SHIPPED",
            "shipped_at": shipped_at, "delivered_at": delivered_at,
            "to_paypal_address": bool(data.get("to_paypal_address", True)),
            "signature_confirmed": bool(data.get("signature_confirmed")) and delivered,
            **({"paypal_tracking_sent_at": None} if tracking_changed else {}),
        })
    record("seller", "order.shipment_recorded", obj=order, paypal_id=order.paypal_order_id,
           carrier=carrier, tracking_number=tracking, status=shipment.status)

    paypal_status = "unchanged"
    if needs_push:
        try:
            result = get_client().add_tracking(order.paypal_order_id, capture.paypal_capture_id, carrier, tracking)
            paypal_status = "simulated" if result.get("simulated") else "sent"
            Shipment.objects.filter(pk=shipment.pk, tracking_number=tracking).update(paypal_tracking_sent_at=timezone.now())
            record("seller", "paypal.tracking_added", obj=order, paypal_id=order.paypal_order_id,
                   capture_id=capture.paypal_capture_id, simulated=paypal_status == "simulated")
        except PayPalError as exc:
            paypal_status = "failed"  # paypal_tracking_sent_at stays empty, so the next save retries
            record("system", "paypal.tracking_failed", obj=order, paypal_id=order.paypal_order_id, error=str(exc)[:300])

    _refresh_open_disputes(order)
    return shipment, paypal_status


def _refresh_open_disputes(order: Order) -> None:
    """Re-draft with the new tracking, but never touch a case that is being sent or failed to send."""
    from disputes import service as copilot
    for dispute in order.disputes.filter(status="WAITING_FOR_SELLER_RESPONSE").select_related("case"):
        case = getattr(dispute, "case", None)
        if case is not None and case.status not in {"READY", "NEEDS_DATA"}:
            continue
        try:
            copilot.prepare(dispute, force=True)
        except Exception as exc:  # a failed re-draft must not lose the saved shipment
            record("system", "copilot.prepare_failed", obj=dispute, paypal_id=dispute.paypal_dispute_id,
                   error=str(exc)[:300])
