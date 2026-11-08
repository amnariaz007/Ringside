"""Webhook pipeline: verification, idempotency, out-of-order delivery, scoring."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from audit.models import AuditEvent
from core.models import Dispute, Order, Refund
from paypal_integration import demo, payloads
from paypal_integration.client import MOCK_VALID_SIGNATURE, MockPayPalClient
from risk.models import RiskAssessment
from webhooks.models import WebhookEvent

pytestmark = pytest.mark.django_db
URL = "/api/webhooks/paypal/"
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def post(client, event, sig=MOCK_VALID_SIGNATURE):
    return client.post(URL, data=json.dumps(event), content_type="application/json",
                       HTTP_PAYPAL_TRANSMISSION_SIG=sig)


def make_order(order_id="ORD1", at=NOW, **kw):
    demo.get_or_create_seller()
    base = dict(merchant_id=demo.MERCHANT_ID, payer_id="P1", email="a.b@gmail.com", given_name="A", surname="B",
                payer_country="US", amount="50.00", created_at=at, ship_line1="1 Oak St", ship_city="Houston",
                ship_postal="77002", ship_country="US", order_id=order_id, capture_id=f"CAP-{order_id}")
    base.update(kw)
    o = payloads.order(**base)
    MockPayPalClient.put("order", o["id"], o)
    return o


def test_capture_event_ingests_and_scores(client):
    o = make_order()
    resp = post(client, payloads.capture_completed_event(o, NOW))
    assert resp.status_code == 200
    order = Order.objects.get(paypal_order_id="ORD1")
    assert order.captures.get().seller_protection_status == "ELIGIBLE"
    assert order.assessments.get().level == "low"
    assert WebhookEvent.objects.get().processed_at is not None
    assert set(AuditEvent.objects.values_list("action", flat=True)) >= {"webhook.received", "order.scored", "risk.explained"}


def test_duplicate_delivery_is_processed_once(client):
    event = payloads.capture_completed_event(make_order(), NOW)
    assert post(client, event).status_code == 200
    resp = post(client, event)
    assert resp.status_code == 200 and "duplicate" in resp.json()["detail"]
    assert Order.objects.count() == 1 and RiskAssessment.objects.count() == 1
    assert WebhookEvent.objects.count() == 1


def test_forged_event_is_rejected_and_not_processed(client):
    resp = post(client, payloads.capture_completed_event(make_order(), NOW), sig="forged")
    assert resp.status_code == 400
    assert Order.objects.count() == 0
    assert WebhookEvent.objects.count() == 0  # forged bodies are never stored
    assert AuditEvent.objects.filter(action="webhook.rejected").exists()


def test_forged_event_cannot_block_the_real_one(client):
    event = payloads.capture_completed_event(make_order(), NOW)
    assert post(client, event, sig="forged").status_code == 400
    assert post(client, event).status_code == 200
    assert WebhookEvent.objects.get().verified is True and Order.objects.count() == 1


def test_malformed_body_is_400(client):
    resp = client.post(URL, data="not json", content_type="application/json",
                       HTTP_PAYPAL_TRANSMISSION_SIG=MOCK_VALID_SIGNATURE)
    assert resp.status_code == 400


def test_get_is_not_allowed(client):
    assert client.get(URL).status_code == 405


def test_refund_before_order_is_deferred_then_succeeds_on_retry(client):
    o = make_order()
    refund = payloads.refund(capture_id="CAP-ORD1", amount="50.00", created_at=NOW + timedelta(days=1))
    refund_event = payloads.webhook_event("PAYMENT.CAPTURE.REFUNDED", refund, resource_type="refund", created_at=NOW)

    first = post(client, refund_event)
    assert first.status_code == 503  # PayPal will redeliver
    assert WebhookEvent.objects.get(event_id=refund_event["id"]).error

    assert post(client, payloads.capture_completed_event(o, NOW)).status_code == 200
    retry = post(client, refund_event)
    assert retry.status_code == 200
    assert Refund.objects.count() == 1
    assert WebhookEvent.objects.get(event_id=refund_event["id"]).error == ""


def test_stale_dispute_update_does_not_overwrite_newer_state(client):
    post(client, payloads.capture_completed_event(make_order(), NOW))
    newer = payloads.dispute(capture_id="CAP-ORD1", amount="50.00", created_at=NOW, dispute_id="PP-D-1",
                             status="RESOLVED", outcome="RESOLVED_SELLER_FAVOUR", updated_at=NOW + timedelta(days=5))
    older = payloads.dispute(capture_id="CAP-ORD1", amount="50.00", created_at=NOW, dispute_id="PP-D-1",
                             updated_at=NOW + timedelta(days=1))

    MockPayPalClient.put("dispute", "PP-D-1", newer)
    post(client, payloads.webhook_event("CUSTOMER.DISPUTE.RESOLVED", newer, resource_type="dispute", created_at=NOW))
    # The older update arrives late; the client still returns the newer object, but even if a
    # stale payload were ingested directly it must not win:
    from paypal_integration.ingest import ingest_dispute
    ingest_dispute(older)
    d = Dispute.objects.get()
    assert d.status == "RESOLVED" and d.outcome == "RESOLVED_SELLER_FAVOUR"


def test_unhandled_event_type_is_acknowledged(client):
    event = payloads.webhook_event("BILLING.PLAN.CREATED", {"id": "X"}, resource_type="plan", created_at=NOW)
    resp = post(client, event)
    assert resp.status_code == 200 and "ignored" in resp.json()["detail"]


def test_velocity_fires_on_third_order_to_one_address_in_ten_minutes(client):
    for i in range(3):
        o = make_order(order_id=f"V{i}", payer_id=f"VP{i}", email=f"v{i}x@gmail.com",
                       at=NOW + timedelta(minutes=3 * i), ship_line1="9 Dock Rd")
        post(client, payloads.capture_completed_event(o, NOW))
    rules_on_third = list(Order.objects.get(paypal_order_id="V2").assessments.get().findings.values_list("rule", flat=True))
    rules_on_second = list(Order.objects.get(paypal_order_id="V1").assessments.get().findings.values_list("rule", flat=True))
    assert "VELOCITY" in rules_on_third and "VELOCITY" not in rules_on_second
