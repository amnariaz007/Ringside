"""
PayPal webhook pipeline:

    verify signature -> store raw event (once, keyed on event id) -> process -> score

Status codes are chosen for PayPal's retry behaviour: any non-2xx makes
PayPal redeliver later (it retries for up to 3 days). So:
  400  forged / malformed     -> stored as unverified, never processed
  503  depends on an event we haven't seen yet (out of order) -> PayPal retries
  200  processed, duplicate, or an event type we ignore
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

from audit.models import record
from core.models import Order
from paypal_integration.client import WEBHOOK_HEADERS, PayPalNotFound, get_client
from paypal_integration.ingest import MissingDependency, ingest_dispute, ingest_order, ingest_refund, redact
from risk.engine import score_order

from .models import WebhookEvent

HANDLED_TYPES = {
    "PAYMENT.CAPTURE.COMPLETED",
    "PAYMENT.CAPTURE.REFUNDED",
    "CUSTOMER.DISPUTE.CREATED",
    "CUSTOMER.DISPUTE.UPDATED",
    "CUSTOMER.DISPUTE.RESOLVED",
}


@dataclass
class Result:
    status: int
    message: str


def handle(raw_body: bytes, headers: dict[str, str], client=None) -> Result:
    """
    Verify, store and process one PayPal webhook. `client` is only passed by the
    in-process demo simulator (a mock client); HTTP deliveries always use
    get_client(), so in sandbox mode they must carry a real PayPal signature.
    """
    try:
        event = json.loads(raw_body)
        event_id, event_type = event["id"], event["event_type"]
    except (ValueError, KeyError, TypeError):
        return Result(400, "malformed event")

    client = client or get_client()
    headers = {k.upper(): v for k, v in headers.items()}
    verified = client.verify_webhook_signature({h: headers.get(h, "") for h in WEBHOOK_HEADERS}, raw_body)

    if not verified:
        # Never store unverified bodies: anyone can POST here. Keep one short audit line.
        record("system", "webhook.rejected", paypal_id=str(event_id)[:64], event_type=str(event_type)[:80])
        return Result(400, "signature verification failed")
    stored, created = _store(event, verified)
    if not created and stored.processed_at:
        return Result(200, "duplicate, already processed")

    record("paypal", "webhook.received", obj=stored, paypal_id=event_id, event_type=event_type)
    try:
        message = _process(event, client)
    except (MissingDependency, PayPalNotFound) as exc:
        stored.error = str(exc)
        stored.save(update_fields=["error"])
        record("system", "webhook.deferred", obj=stored, paypal_id=event_id, reason=str(exc))
        return Result(503, f"deferred: {exc}")

    stored.processed_at = timezone.now()
    stored.error = ""
    stored.save(update_fields=["processed_at", "error"])
    return Result(200, message)


def _store(event: dict, verified: bool) -> tuple[WebhookEvent, bool]:
    resource = event.get("resource") or {}
    defaults = {
        "event_type": event["event_type"],
        "resource_id": str(resource.get("id") or resource.get("dispute_id") or ""),
        "raw": event | {"resource": redact(event.get("resource") or {})},
        "verified": verified,
    }
    try:
        with transaction.atomic():
            return WebhookEvent.objects.get_or_create(event_id=event["id"], defaults=defaults)
    except IntegrityError:
        # Two deliveries raced; the other one won the insert.
        return WebhookEvent.objects.get(event_id=event["id"]), False


def _process(event: dict, client) -> str:
    event_type, resource = event["event_type"], event.get("resource") or {}

    if event_type not in HANDLED_TYPES:
        return f"ignored {event_type}"

    if event_type == "PAYMENT.CAPTURE.COMPLETED":
        order_id = resource.get("supplementary_data", {}).get("related_ids", {}).get("order_id")
        if not order_id:
            raise MissingDependency("capture event has no related order_id")
        order, assessment = ingest_and_score(client.get_order(order_id))
        if assessment:
            return f"order {order.paypal_order_id} scored {assessment.score} ({assessment.level})"
        return f"order {order.paypal_order_id} already scored"

    if event_type == "PAYMENT.CAPTURE.REFUNDED":
        refund = ingest_refund(resource)
        record("paypal", "refund.recorded", obj=refund, paypal_id=refund.paypal_refund_id, amount=str(refund.amount))
        return f"refund {refund.paypal_refund_id} recorded"

    # Disputes: re-fetch the full object; webhook resources can be partial.
    dispute = apply_dispute(client.get_dispute(resource["dispute_id"]))
    return f"dispute {dispute.paypal_dispute_id} {dispute.status}"


def ingest_and_score(order_json: dict):
    """
    Store a paid order and score it once. Used by the capture webhook and by the
    shop right after checkout, whichever comes first. Returns (order, new
    assessment or None if it was already scored).
    """
    order, _ = ingest_order(order_json)
    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        if locked.assessments.exists():
            return order, None
        return order, score_order(locked)


def apply_dispute(dispute_json: dict):
    """Store a dispute and start the copilot when PayPal is waiting for the seller."""
    dispute, created = ingest_dispute(dispute_json)
    record(
        "paypal", "dispute.created" if created else "dispute.updated", obj=dispute,
        paypal_id=dispute.paypal_dispute_id, status=dispute.status, reason=dispute.reason,
    )
    case_status = getattr(getattr(dispute, "case", None), "status", None)
    waiting = dispute.status == "WAITING_FOR_SELLER_RESPONSE"
    # Start when the seller first has to act: on arrival, or later if the
    # dispute only reached this stage after an inquiry (common in the sandbox),
    # or again once a dispute that was missing its order can be linked.
    if waiting and (case_status is None or (case_status == "NEEDS_DATA" and dispute.order_id)):
        _start_copilot(dispute)
    return dispute


def _start_copilot(dispute) -> None:
    """Prepare the evidence and draft now, so the seller finds them ready. Never submits anything."""
    from django.conf import settings

    from disputes import service as copilot

    if settings.COPILOT_RUNNER == "inline":
        try:
            copilot.prepare(dispute, force=getattr(getattr(dispute, "case", None), "status", "") == "NEEDS_DATA")
        except Exception as exc:  # the copilot must never make PayPal retry a good webhook
            record("system", "copilot.prepare_failed", obj=dispute, paypal_id=dispute.paypal_dispute_id,
                   error=str(exc)[:500])
