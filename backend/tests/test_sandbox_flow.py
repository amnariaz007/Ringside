"""
Real sandbox flow: the shop is linked to the sandbox business account, buyers pay
through the Juniper Lane checkout, the seller records tracking, and seeded
(simulated) records keep working next to real ones. No test calls PayPal.
"""

import json
from datetime import timedelta
from decimal import Decimal
from unittest import mock

import pytest
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.test import Client
from django.utils import timezone

from audit.models import AuditEvent
from core.models import Dispute, Order, Seller, Shipment
from disputes.models import DisputeCase
from paypal_integration import demo, payloads
from paypal_integration.client import MockPayPalClient, PayPalError, RoutingClient, get_client
from paypal_integration.sellers import DEMO_MERCHANT_ID, get_or_create_seller, seller_for
from shop.catalog import CartError, build_purchase_unit
from webhooks import service

pytestmark = pytest.mark.django_db
REAL = "REALMERCHANT9"


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()


@pytest.fixture
def sandbox_mode(settings):
    settings.PAYPAL_MODE = "sandbox"
    settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET = "client-id", "secret"
    settings.PAYPAL_WEBHOOK_ID = "WH-1"
    settings.PAYPAL_MERCHANT_ID = REAL
    return settings


@pytest.fixture
def no_network():
    """Any real HTTP call fails the test."""
    with mock.patch("paypal_integration.client.requests.request", side_effect=AssertionError("network")), \
         mock.patch("paypal_integration.client.requests.post", side_effect=AssertionError("network")):
        yield


def real_order(order_id="5O190127TN364715T", amount="86.00", merchant=REAL):
    o = payloads.order(merchant_id=merchant, payer_id="SBXBUYER01", email="buyer@personal.example.com",
                       given_name="Sandbox", surname="Buyer", payer_country="US", amount=amount,
                       created_at=timezone.now() - timedelta(minutes=2), ship_line1="1 Main St",
                       ship_city="San Jose", ship_postal="95131", ship_state="CA", ship_country="US",
                       order_id=order_id, capture_id="3C679366HH908993F")
    return o


class FakeSandbox:
    """Stands in for SandboxPayPalClient: records calls, returns canned PayPal responses."""

    def __init__(self, order=None):
        self.order = order or real_order()
        self.calls = []

    def create_order(self, unit):
        self.calls.append(("create", unit))
        return {"id": self.order["id"], "status": "CREATED"}

    def capture_order(self, order_id):
        self.calls.append(("capture", order_id))
        return {"id": order_id, "status": "COMPLETED"}

    def get_order(self, order_id):
        self.calls.append(("get_order", order_id))
        return self.order

    def get_dispute(self, dispute_id):
        raise AssertionError("unexpected")

    def add_tracking(self, order_id, capture_id, carrier, tracking):
        self.calls.append(("track", order_id, capture_id, carrier, tracking))
        return {"id": order_id}

    def verify_webhook_signature(self, headers, raw):
        self.calls.append(("verify",))
        return False


# --- linking the demo shop to the sandbox business account -----------------------------

def test_seller_is_relinked_to_the_real_merchant_id(sandbox_mode):
    sandbox_mode.PAYPAL_MERCHANT_ID = ""
    placeholder = get_or_create_seller()
    assert placeholder.paypal_merchant_id == DEMO_MERCHANT_ID
    sandbox_mode.PAYPAL_MERCHANT_ID = REAL
    linked = get_or_create_seller()
    assert linked.pk == placeholder.pk and linked.paypal_merchant_id == REAL
    assert Seller.objects.count() == 1
    assert AuditEvent.objects.filter(action="seller.linked_to_paypal").count() == 1


def test_first_real_order_links_the_shop_without_a_manual_step(sandbox_mode):
    sandbox_mode.PAYPAL_MERCHANT_ID = ""
    get_or_create_seller()
    sandbox_mode.PAYPAL_MERCHANT_ID = REAL
    assert seller_for(REAL).paypal_merchant_id == REAL
    assert seller_for("SOMEONEELSE") is None


def test_seeded_history_follows_the_linked_account(sandbox_mode, no_network):
    demo.seed_history()
    assert set(Order.objects.values_list("seller__paypal_merchant_id", flat=True)) == {REAL}


# --- routing: simulated records stay simulated in sandbox mode --------------------------

def test_get_client_routes_in_sandbox_mode(sandbox_mode):
    assert isinstance(get_client(), RoutingClient)


def test_routing_sends_seeded_ids_to_the_mock_and_others_to_paypal(sandbox_mode):
    MockPayPalClient.put("dispute", "PP-D-SEEDED", {"dispute_id": "PP-D-SEEDED"})
    fake = FakeSandbox()
    router = RoutingClient(sandbox=fake, mock=MockPayPalClient())
    assert router.get_dispute("PP-D-SEEDED") == {"dispute_id": "PP-D-SEEDED"}
    assert router.get_order("5O190127TN364715T")["id"] == "5O190127TN364715T"
    assert ("get_order", "5O190127TN364715T") in fake.calls
    assert router.verify_webhook_signature({}, b"{}") is False and ("verify",) in fake.calls


def test_simulator_still_works_in_sandbox_mode_without_network(sandbox_mode, no_network):
    demo.seed_history()
    for name in ("normal", "scammer", "ring", "dispute"):
        assert demo.live_scenario(name).status == 200
    case = DisputeCase.objects.get()
    assert case.status == "READY"


def test_seeded_dispute_submits_to_the_simulator_in_sandbox_mode(sandbox_mode, no_network, client):
    demo.seed_history()
    demo.live_scenario("dispute")
    case = DisputeCase.objects.get()
    r = client.post(f"/api/disputes/{case.dispute_id}/copilot/submit/",
                    data={"action": case.recommendation, "text": case.draft_text, "confirm": True},
                    content_type="application/json")
    assert r.status_code == 200, r.json()
    assert r.json()["status"] == "SUBMITTED"


def test_forged_http_webhook_is_checked_by_paypal_in_sandbox_mode(sandbox_mode, client):
    event = payloads.capture_completed_event(real_order(), timezone.now())
    with mock.patch("paypal_integration.client.SandboxPayPalClient.verify_webhook_signature", return_value=False) as v:
        r = client.post("/api/webhooks/paypal/", data=json.dumps(event), content_type="application/json",
                        HTTP_PAYPAL_TRANSMISSION_SIG="mock-valid-signature")
    assert r.status_code == 400 and v.called
    assert not Order.objects.exists()


def test_real_capture_webhook_scores_a_real_order(sandbox_mode):
    get_or_create_seller()
    fake = FakeSandbox()
    event = payloads.capture_completed_event(fake.order, timezone.now())
    with mock.patch("webhooks.service.get_client", return_value=RoutingClient(sandbox=fake, mock=MockPayPalClient())), \
         mock.patch.object(FakeSandbox, "verify_webhook_signature", return_value=True):
        result = service.handle(json.dumps(event).encode(), {})
    assert result.status == 200 and "scored" in result.message
    assert Order.objects.get(paypal_order_id=fake.order["id"]).seller.paypal_merchant_id == REAL


def test_dispute_that_reaches_waiting_later_starts_the_copilot(no_network):
    demo.seed_history()
    capture = Order.objects.filter(shipment__status="DELIVERED").first().captures.first()
    d = payloads.dispute(capture_id=capture.paypal_capture_id, amount=capture.amount,
                         created_at=timezone.now(), status="UNDER_REVIEW")
    service.apply_dispute(d)
    assert not DisputeCase.objects.exists()
    d.update(status="WAITING_FOR_SELLER_RESPONSE", update_time=(timezone.now() + timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    service.apply_dispute(d)
    assert DisputeCase.objects.get().status == "READY"


# --- the Juniper Lane checkout -----------------------------------------------------------

def test_cart_is_priced_on_the_server():
    unit = build_purchase_unit([{"sku": "JL-LINEN-SHIRT", "quantity": 2, "price": "0.01"},
                                {"sku": "JL-WOOL-BEANIE", "quantity": 1}])
    assert unit["amount"]["value"] == "144.00"
    assert unit["amount"]["breakdown"]["item_total"]["value"] == "144.00"
    assert sum(Decimal(i["unit_amount"]["value"]) * int(i["quantity"]) for i in unit["items"]) == Decimal("144.00")


@pytest.mark.parametrize("items", [
    [], None, "x", [{"sku": "NOPE", "quantity": 1}], [{"sku": "JL-LINEN-SHIRT", "quantity": 0}],
    [{"sku": "JL-LINEN-SHIRT", "quantity": 6}], [{"sku": "JL-LINEN-SHIRT", "quantity": True}],
    [{"sku": "JL-LINEN-SHIRT", "quantity": "2"}], [{"sku": "JL-LINEN-SHIRT", "quantity": 1.5}],
    [{"sku": "JL-LINEN-SHIRT", "quantity": 3}, {"sku": "JL-LINEN-SHIRT", "quantity": 3}],
    [{"sku": "JL-LINEN-SHIRT", "quantity": 1}] * 7,
])
def test_bad_carts_are_refused(items):
    with pytest.raises(CartError):
        build_purchase_unit(items)


def anon():
    c = Client(enforce_csrf_checks=True)
    c.get("/api/shop/")
    return c, {"HTTP_X_CSRFTOKEN": c.cookies["csrftoken"].value}


def test_shop_info_is_public_and_hides_the_client_id_in_mock_mode():
    r = Client().get("/api/shop/")
    assert r.status_code == 200
    body = r.json()
    assert body["checkout_enabled"] is False and body["paypal_client_id"] == ""
    assert len(body["products"]) == 4


def test_checkout_is_closed_in_mock_mode():
    c, h = anon()
    r = c.post("/api/shop/orders/", data={"items": [{"sku": "JL-LINEN-SHIRT", "quantity": 1}]},
               content_type="application/json", **h)
    assert r.status_code == 409


def test_create_order_needs_csrf(sandbox_mode):
    c = Client(enforce_csrf_checks=True)
    r = c.post("/api/shop/orders/", data={"items": [{"sku": "JL-LINEN-SHIRT", "quantity": 1}]},
               content_type="application/json")
    assert r.status_code == 403


def test_create_order_sends_the_server_priced_unit(sandbox_mode):
    fake = FakeSandbox()
    c, h = anon()
    with mock.patch("shop.views.get_client", return_value=fake):
        r = c.post("/api/shop/orders/", data={"items": [{"sku": "JL-FIELD-JACKET", "quantity": 1}]},
                   content_type="application/json", **h)
    assert r.status_code == 200 and r.json() == {"id": fake.order["id"]}
    assert fake.calls[0][1]["amount"]["value"] == "148.00"


def test_capture_ingests_and_scores_but_tells_the_buyer_nothing_about_risk(sandbox_mode):
    get_or_create_seller()
    fake = FakeSandbox()
    c, h = anon()
    with mock.patch("shop.views.get_client", return_value=fake):
        r = c.post(f"/api/shop/orders/{fake.order['id']}/capture/", **h)
    assert r.status_code == 200
    assert r.json() == {"status": "COMPLETED", "order_id": fake.order["id"]}
    order = Order.objects.get(paypal_order_id=fake.order["id"])
    assert order.assessments.count() == 1
    # The capture webhook arriving afterwards doesn't score it twice.
    service.ingest_and_score(fake.order)
    assert order.assessments.count() == 1


def test_capture_retry_after_already_captured_still_succeeds(sandbox_mode):
    get_or_create_seller()
    fake = FakeSandbox()
    fake.capture_order = mock.Mock(side_effect=PayPalError("422 UNPROCESSABLE_ENTITY ORDER_ALREADY_CAPTURED"))
    c, h = anon()
    with mock.patch("shop.views.get_client", return_value=fake):
        r = c.post(f"/api/shop/orders/{fake.order['id']}/capture/", **h)
    assert r.status_code == 200


def test_declined_card_asks_the_buyer_to_retry(sandbox_mode):
    fake = FakeSandbox()
    fake.capture_order = mock.Mock(side_effect=PayPalError("422 INSTRUMENT_DECLINED"))
    c, h = anon()
    with mock.patch("shop.views.get_client", return_value=fake):
        r = c.post(f"/api/shop/orders/{fake.order['id']}/capture/", **h)
    assert r.status_code == 402 and r.json()["retry"] is True
    assert not Order.objects.exists()


def test_capture_rejects_odd_order_ids(sandbox_mode):
    c, h = anon()
    assert c.post("/api/shop/orders/abc/capture/", **h).status_code == 404


def test_checkout_is_rate_limited(sandbox_mode):
    fake = FakeSandbox()
    c, h = anon()
    body = {"items": [{"sku": "JL-WOOL-BEANIE", "quantity": 1}]}
    with mock.patch("shop.views.get_client", return_value=fake):
        codes = [c.post("/api/shop/orders/", data=body, content_type="application/json", **h).status_code
                 for _ in range(21)]
    assert codes[:20] == [200] * 20 and codes[20] == 429


# --- "Mark as shipped" ---------------------------------------------------------------------

def unshipped_order():
    demo.seed_history()
    order = Order.objects.filter(captures__status="COMPLETED").first()
    Shipment.objects.filter(order=order).delete()
    return order


def ship(client, order, **body):
    data = {"carrier": "USPS", "tracking_number": "9400100000000000000000", "delivered": False, **body}
    return client.post(f"/api/orders/{order.pk}/shipment/", data=data, content_type="application/json")


def test_mark_as_shipped_saves_and_sends_tracking(client):
    order = unshipped_order()
    r = ship(client, order)
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["paypal_tracking"] == "simulated"  # a seeded order: tracked on the simulator
    assert body["shipment"]["tracking_number"] == "9400100000000000000000"
    assert body["shipment"]["status"] == "SHIPPED"
    trackers = MockPayPalClient().get_order(order.paypal_order_id)["trackers"]
    assert trackers[0]["carrier"] == "USPS"
    assert AuditEvent.objects.filter(action="order.shipment_recorded", actor="seller").exists()


def test_tracking_goes_to_paypal_for_real_orders(sandbox_mode, client):
    get_or_create_seller()
    fake = FakeSandbox()
    service.ingest_and_score(fake.order)
    order = Order.objects.get(paypal_order_id=fake.order["id"])
    with mock.patch("core.shipping.get_client", return_value=RoutingClient(sandbox=fake, mock=MockPayPalClient())):
        r = ship(client, order, carrier="UPS", tracking_number="1Z999AA10123456784")
    assert r.json()["paypal_tracking"] == "sent"
    assert ("track", order.paypal_order_id, "3C679366HH908993F", "UPS", "1Z999AA10123456784") in fake.calls


def test_paypal_tracking_failure_keeps_the_shipment(client):
    order = unshipped_order()
    with mock.patch("paypal_integration.client.MockPayPalClient.add_tracking", side_effect=PayPalError("boom")):
        r = ship(client, order)
    assert r.status_code == 200 and r.json()["paypal_tracking"] == "failed"
    assert Shipment.objects.filter(order=order).exists()


def test_unchanged_tracking_is_not_resent(client):
    order = unshipped_order()
    ship(client, order)
    r = ship(client, order, delivered=True)
    assert r.json()["paypal_tracking"] == "unchanged"
    assert r.json()["shipment"]["status"] == "DELIVERED"
    assert len(MockPayPalClient().get_order(order.paypal_order_id)["trackers"]) == 1


@pytest.mark.parametrize("body", [
    {"carrier": "PIGEON"}, {"tracking_number": "12"}, {"tracking_number": "abc_def_ghi"},
    {"tracking_number": "<script>"}, {"shipped_at": "not-a-date"},
    {"shipped_at": (timezone.now() + timedelta(days=2)).isoformat()},
    {"delivered": True, "shipped_at": timezone.now().isoformat(),
     "delivered_at": (timezone.now() - timedelta(days=1)).isoformat()},
    {"shipped_at": "2001-01-01T00:00:00+00:00"},
])
def test_bad_shipments_are_refused(client, body):
    order = unshipped_order()
    assert ship(client, order, **body).status_code == 400
    assert not Shipment.objects.filter(order=order).exists()


def test_unpaid_order_cannot_be_shipped(client):
    order = unshipped_order()
    order.captures.update(status="DECLINED")
    assert ship(client, order).status_code == 400


def test_shipping_needs_login():
    order = unshipped_order()
    assert ship(Client(), order).status_code == 403


def test_adding_tracking_redrafts_an_open_dispute(client):
    demo.seed_history()
    demo.live_scenario("dispute")
    case = DisputeCase.objects.select_related("dispute__order").get()
    Shipment.objects.filter(order=case.dispute.order).delete()
    from disputes import service as copilot
    case = copilot.prepare(case.dispute, force=True)
    assert case.recommendation == "ACCEPT"
    ship(client, case.dispute.order, delivered=True, signature_confirmed=True)
    case.refresh_from_db()
    assert case.recommendation == "FIGHT"
    assert any(e["kind"] == "tracking" and e["supports"] == "fight" for e in case.evidence)


# --- management commands ---------------------------------------------------------------------

def test_dispute_command_refuses_mock_mode():
    with pytest.raises(CommandError):
        call_command("paypal_dispute", "PP-D-1", "--sync")


def test_connect_command_discovers_the_merchant_id(sandbox_mode, capsys):
    sandbox_mode.PAYPAL_MERCHANT_ID = ""
    with mock.patch("paypal_integration.client.SandboxPayPalClient._access_token", return_value="t"), \
         mock.patch("paypal_integration.client.SandboxPayPalClient.create_order",
                    return_value={"purchase_units": [{"payee": {"merchant_id": "FOUNDIT123"}}]}):
        call_command("connect_paypal", "--discover")
    out = capsys.readouterr().out
    assert "PAYPAL_MERCHANT_ID=FOUNDIT123" in out
    assert "secret" not in out.lower() or "client id + secret" in out.lower()


def test_health_reports_setup_as_booleans_only(sandbox_mode):
    body = Client().get("/api/health/").json()
    assert body["paypal_setup"] == {"keys": True, "webhook_id": True, "merchant_id": True}
    assert "client-id" not in json.dumps(body) and REAL not in json.dumps(body)


def test_dispute_on_unknown_capture_is_deferred(sandbox_mode):
    d = payloads.dispute(capture_id="UNKNOWNCAP", amount="10.00", created_at=timezone.now())
    with pytest.raises(Exception):
        service.apply_dispute(d)
    assert not Dispute.objects.exists()


# --- fixes from the independent review ------------------------------------------------------

def test_tracking_with_spaces_is_normalised(client):
    order = unshipped_order()
    r = ship(client, order, tracking_number=" 9400 1000 0000 0000 0000 00 ")
    assert r.status_code == 200
    assert r.json()["shipment"]["tracking_number"] == "9400100000000000000000"


def test_editing_a_shipment_keeps_its_real_dates(client):
    order = Order.objects.none()
    demo.seed_history()
    order = Order.objects.filter(shipment__status="DELIVERED").first()
    before = Shipment.objects.get(order=order)
    r = ship(client, order, carrier=before.carrier, tracking_number=before.tracking_number, delivered=True)
    assert r.status_code == 200
    after = Shipment.objects.get(order=order)
    assert after.shipped_at == before.shipped_at and after.delivered_at == before.delivered_at


def test_failed_tracking_push_is_retried_on_the_next_save(client):
    order = unshipped_order()
    with mock.patch("paypal_integration.client.MockPayPalClient.add_tracking", side_effect=PayPalError("boom")):
        assert ship(client, order).json()["paypal_tracking"] == "failed"
    assert Shipment.objects.get(order=order).paypal_tracking_sent_at is None
    assert ship(client, order).json()["paypal_tracking"] == "simulated"
    assert Shipment.objects.get(order=order).paypal_tracking_sent_at is not None
    assert ship(client, order).json()["paypal_tracking"] == "unchanged"


def test_shipping_does_not_redraft_a_failed_submission(client):
    demo.seed_history()
    demo.live_scenario("dispute")
    case = DisputeCase.objects.select_related("dispute__order").get()
    DisputeCase.objects.filter(pk=case.pk).update(status="FAILED", error="PayPal timeout")
    ship(client, case.dispute.order, carrier="UPS", tracking_number="1Z999AA10123456784")
    case.refresh_from_db()
    assert case.status == "FAILED" and case.error == "PayPal timeout"


def test_a_case_being_prepared_is_not_prepared_twice(no_network):
    from disputes import service as copilot
    demo.seed_history()
    demo.live_scenario("dispute")
    case = DisputeCase.objects.get()
    DisputeCase.objects.filter(pk=case.pk).update(status="PREPARING")
    with mock.patch("disputes.service.step_gather") as gather:
        copilot.prepare(case.dispute)
    assert not gather.called


def capture_with(fake, status):
    fake.order["purchase_units"][0]["payments"]["captures"][0]["status"] = status
    c, h = anon()
    with mock.patch("shop.views.get_client", return_value=fake):
        return c.post(f"/api/shop/orders/{fake.order['id']}/capture/", **h)


def test_pending_capture_is_reported_as_pending(sandbox_mode):
    get_or_create_seller()
    r = capture_with(FakeSandbox(), "PENDING")
    assert r.status_code == 202 and r.json()["status"] == "PENDING" and r.json()["order_id"]


def test_declined_capture_inside_a_completed_order_is_a_decline(sandbox_mode):
    r = capture_with(FakeSandbox(), "DECLINED")
    assert r.status_code == 402 and r.json()["retry"] is True
    assert not Order.objects.exists()


def test_capture_lookup_failure_still_returns_the_order_id(sandbox_mode):
    fake = FakeSandbox()
    fake.get_order = mock.Mock(side_effect=PayPalError("timeout"))
    c, h = anon()
    with mock.patch("shop.views.get_client", return_value=fake):
        r = c.post(f"/api/shop/orders/{fake.order['id']}/capture/", **h)
    assert r.status_code == 202 and r.json()["order_id"] == fake.order["id"]


def test_ingest_crash_after_capture_does_not_500(sandbox_mode):
    fake = FakeSandbox()
    c, h = anon()
    with mock.patch("shop.views.get_client", return_value=fake), \
         mock.patch("shop.views.ingest_and_score", side_effect=RuntimeError("db down")):
        r = c.post(f"/api/shop/orders/{fake.order['id']}/capture/", **h)
    assert r.status_code == 200


def test_correcting_a_wrong_merchant_id_relinks_the_same_shop(sandbox_mode):
    sandbox_mode.PAYPAL_MERCHANT_ID = "WRONGID1"
    first = get_or_create_seller()
    sandbox_mode.PAYPAL_MERCHANT_ID = REAL
    fixed = get_or_create_seller()
    assert fixed.pk == first.pk and fixed.paypal_merchant_id == REAL and Seller.objects.count() == 1


def test_connect_refuses_to_link_a_mismatched_merchant_id(sandbox_mode):
    get_or_create_seller_before = Seller.objects.count()
    with mock.patch("paypal_integration.client.SandboxPayPalClient._access_token", return_value="t"), \
         mock.patch("paypal_integration.client.SandboxPayPalClient.create_order",
                    return_value={"purchase_units": [{"payee": {"merchant_id": "OTHER123"}}]}):
        with pytest.raises(CommandError):
            call_command("connect_paypal", "--discover")
    assert Seller.objects.count() == get_or_create_seller_before


def test_webhook_verification_body_is_utf8_bytes(sandbox_mode):
    from paypal_integration.client import SandboxPayPalClient
    headers = {h: "x" for h in ("PAYPAL-AUTH-ALGO", "PAYPAL-CERT-URL", "PAYPAL-TRANSMISSION-ID",
                                "PAYPAL-TRANSMISSION-SIG", "PAYPAL-TRANSMISSION-TIME")}
    raw = '{"id":"WH-1","note":"didn’t arrive ✉"}'.encode()
    with mock.patch.object(SandboxPayPalClient, "_request", return_value={"verification_status": "SUCCESS"}) as req:
        assert SandboxPayPalClient().verify_webhook_signature(headers, raw) is True
    body = req.call_args.kwargs["data"]
    assert isinstance(body, bytes) and raw in body
