"""Regression tests for the copilot code review (docs/VERIFICATION.md, day 3). Each bypass string was proven by a reviewer."""

import json
from decimal import Decimal
from unittest import mock

import pytest

from audit.models import AuditEvent
from core.models import Dispute, Order
from disputes import evidence, guard, recommend, service
from disputes.models import DisputeCase
from paypal_integration import demo, payloads
from paypal_integration.client import MockPayPalClient
from paypal_integration.ingest import ingest_dispute

pytestmark = pytest.mark.django_db

EV = [
    {"id": "E1", "kind": "order", "detail": "PayPal order 5O190127TN364715T for USD 129.00, placed 3 Nov 2026.", "data": {}},
    {"id": "E2", "kind": "tracking", "detail": "The order shipped on 4 Nov 2026 with UPS, tracking number 9400111899223344556677.", "data": {}},
    {"id": "E3", "kind": "delivery", "detail": "UPS confirmed delivery on 8 Nov 2026.", "data": {}},
    {"id": "E4", "kind": "buyer_history", "detail": "This payer has 2 earlier delivered orders from this shop with no dispute or refund so far.", "data": {}},
    {"id": "E5", "kind": "ring", "detail": "Shares address with 3 accounts that refunded or disputed.", "data": {}},
]
BASE = ("The order shipped on 4 Nov 2026 with UPS, tracking number 9400111899223344556677 [E2]. "
        "UPS confirmed delivery on 8 Nov 2026 [E3]. Please close the case in the seller's favour.")


def test_baseline_draft_passes():
    assert guard.check(BASE, "FIGHT", EV) == []


def test_copied_evidence_sentence_with_refund_word_is_allowed():
    text = BASE + " This payer has 2 earlier delivered orders from this shop with no dispute or refund so far [E4]."
    assert guard.check(text, "FIGHT", EV) == []


# Finding 1: conceding wording
@pytest.mark.parametrize("extra", [
    "We'll refund the buyer the entire payment.",
    "We do not contest this case and agree the buyer should be reimbursed.",
    "We are happy to accept this dispute and return the full amount of the payment.",
    "We will process a complete refund today.",
    "We won't dispute this any further.",
])
def test_conceding_variants_rejected(extra):
    assert any("concedes" in p for p in guard.check(BASE + " " + extra, "FIGHT", EV))


# Findings 2 and 3: invented numbers in any format; no substring matching
@pytest.mark.parametrize("extra", [
    "Replacement tracking 9400.1118.9922.0001 was also issued.",
    "The buyer previously received USD 1,250.00 in credit.",
    "A second parcel shipped on 12/11/2026.",
    "It was resent under tracking 1899 2233 4455.",
    "The buyer confirmed by phone on 715-129-0032.",
    "We also gave USD 90.00 store credit.",
    "The buyer has twelve other orders.",
])
def test_invented_numbers_rejected(extra):
    problems = guard.check(BASE + " " + extra, "FIGHT", EV)
    assert any("number" in p for p in problems), problems


# Finding 4: citation forms
@pytest.mark.parametrize("text,problem", [
    (BASE + " Seller protection applies [E1, E9].", "doesn't exist"),
    (BASE + " The buyer admitted receipt [B1, E1].", "buyer message"),
    (BASE + " The buyer admitted receipt (B1).", "buyer message"),
    (BASE + " See (E2) again.", "single-id form"),
])
def test_citation_forms(text, problem):
    assert any(problem in p for p in guard.check(text, "FIGHT", EV))


def test_strip_citations_all_forms():
    assert guard.strip_citations("Shipped [E2]. Delivered (E3). Both [E2, E3].") == "Shipped. Delivered. Both."


# Finding 23: internal context (risk score, ring links) can't be cited or sent
def test_citing_internal_ring_context_rejected():
    assert any("internal" in p for p in guard.check(BASE + " The buyer is part of a fraud ring [E5].", "FIGHT", EV))


def test_gemini_never_sees_internal_evidence():
    from ai import gemini
    reply = mock.Mock(status_code=200)
    reply.json.return_value = {"candidates": [{"content": {"parts": [{"text": json.dumps({"draft": BASE, "cited": []})}]}}]}
    with mock.patch("ai.gemini.requests.post", return_value=reply) as post:
        gemini.GeminiProvider(model="m", api_key="k").draft_dispute(
            action="FIGHT", reason=recommend.INR, evidence=EV, buyer_messages=[], offer_amount=None, currency="USD")
    sent = post.call_args.kwargs["json"]["contents"][0]["parts"][0]["text"]
    assert "E5" not in sent and "Shares address" not in sent


# Finding 5: partial refund drafts must state exactly the offer
def test_partial_refund_must_state_offer_and_nothing_more():
    ok = "We're sorry the item on PayPal order 5O190127TN364715T [E1] wasn't right. We offer a partial refund of USD 38.70."
    assert guard.check(ok, "PARTIAL_REFUND", EV, offer_amount=Decimal("38.70"), currency="USD") == []
    wrong = ok.replace("38.70", "90.00")
    assert guard.check(wrong, "PARTIAL_REFUND", EV, offer_amount=Decimal("38.70"), currency="USD")
    full = ok + " We accept the claim and will issue a full refund."
    assert any("more than the partial" in p for p in
               guard.check(full, "PARTIAL_REFUND", EV, offer_amount=Decimal("38.70"), currency="USD"))


# Finding 6: short AI texts with formatted or worded numbers
def test_ring_summary_inflated_amount_rejected():
    from ai.gemini import _check_grounded
    source = json.dumps({"buyers": 3, "refunds": 2, "refunded_amount": "250.00"})
    assert _check_grounded("3 accounts cost you USD 1,250.00 in refunds.", source, 400)
    assert _check_grounded("3 accounts caused twelve refunds.", source, 400)
    assert _check_grounded("3 accounts caused 2 refunds worth USD 250.00.", source, 400) == []


# Findings 12 and 17: currency minor units
def test_zero_decimal_currency_offer():
    assert recommend.suggested_offer(Decimal("10001"), "JPY") == Decimal("3000")
    assert recommend.suggested_offer(Decimal("67.15"), "USD") == Decimal("20.15")
    assert recommend.suggested_offer(Decimal("0.01"), "USD") is None


# Finding 22: buyer contact details masked before storage or AI
def test_buyer_message_contact_details_masked():
    text = "Never arrived. Call me on +1 415 555 0100 or jane.doe@gmail.com, see https://evil.example/x"
    out = evidence.redact_text(text)
    assert "415" not in out and "jane.doe" not in out and "evil.example" not in out


# --- workflow fixes (need a seeded case) ---------------------------------------------

@pytest.fixture
def case():
    demo.seed_history()
    demo.live_scenario("dispute")
    return DisputeCase.objects.select_related("dispute").get()


def post(client, case, **body):
    return client.post(f"/api/disputes/{case.dispute_id}/copilot/submit/", data=json.dumps(body),
                       content_type="application/json")


# Finding 7: any exception during the PayPal call -> FAILED, never stuck in SUBMITTING
def test_timeout_marks_failed(client, case):
    import requests
    with mock.patch.object(MockPayPalClient, "provide_evidence", side_effect=requests.Timeout("slow")):
        body = post(client, case, action="FIGHT", text=case.draft_text, confirm=True).json()
    assert body["status"] == "FAILED" and "Timeout" in body["error"]


# Finding 7 (retry half): a retry after a failure that actually reached PayPal doesn't send twice
def test_retry_reconciles_instead_of_resending(client, case):
    real = MockPayPalClient.provide_evidence

    def sent_then_failed(self, *a, **k):
        real(self, *a, **k)
        raise RuntimeError("connection reset after send")

    with mock.patch.object(MockPayPalClient, "provide_evidence", sent_then_failed):
        assert post(client, case, action="FIGHT", text=case.draft_text, confirm=True).json()["status"] == "FAILED"
    with mock.patch.object(MockPayPalClient, "provide_evidence", side_effect=AssertionError("must not resend")):
        body = post(client, case, action="FIGHT", text=case.draft_text, confirm=True).json()
    assert body["status"] == "SUBMITTED"
    assert AuditEvent.objects.filter(action="copilot.reconciled").exists()


# Finding 8: a failed refresh after success still records SUBMITTED
def test_refresh_failure_keeps_submitted(client, case):
    real_get = MockPayPalClient.get_dispute
    calls = {"n": 0}

    def flaky(self, dispute_id):
        calls["n"] += 1
        if calls["n"] >= 1:
            raise RuntimeError("PayPal 503")
        return real_get(self, dispute_id)

    with mock.patch.object(MockPayPalClient, "get_dispute", flaky):
        with mock.patch.object(MockPayPalClient, "provide_evidence", return_value={"links": []}):
            body = post(client, case, action="FIGHT", text=case.draft_text, confirm=True).json()
    assert body["status"] == "SUBMITTED"
    assert AuditEvent.objects.filter(action="copilot.refresh_failed").exists()


# Finding 9: viewing a FAILED case doesn't silently re-draft it
def test_get_does_not_reprepare_failed_case(client, case):
    DisputeCase.objects.filter(pk=case.pk).update(status="FAILED", error="sandbox 500", draft_text="seller's text here")
    body = client.get(f"/api/disputes/{case.dispute_id}/copilot/").json()
    assert body["status"] == "FAILED" and body["draft_text"] == "seller's text here"


# Finding 10: a regenerate finishing after a submit started can't overwrite SUBMITTING
def test_draft_step_does_not_overwrite_submitting(case):
    case.status = "PREPARING"
    case.save()
    DisputeCase.objects.filter(pk=case.pk).update(status="SUBMITTING")
    service.step_draft(case)
    assert DisputeCase.objects.get(pk=case.pk).status == "SUBMITTING"


# Finding 11: dispute without an order waits for data instead of recommending
def test_dispute_without_order_needs_data():
    demo.get_or_create_seller()
    from datetime import datetime, timezone
    d = payloads.dispute(capture_id="", amount="50.00", created_at=datetime(2026, 11, 8, tzinfo=timezone.utc))
    d["disputed_transactions"] = []
    dispute, _ = ingest_dispute(d)
    case = service.prepare(dispute)
    assert case.status == "NEEDS_DATA" and case.recommendation == ""


# Finding 12: seller-chosen partial refund with their own amount, validated
def test_seller_partial_refund_amount(client, case):
    text = "We're sorry. We'd like to offer a partial refund of USD 10.00 and the buyer can keep the item."
    assert post(client, case, action="PARTIAL_REFUND", text=text, offer_amount="999", confirm=True).status_code == 409
    body = post(client, case, action="PARTIAL_REFUND", text=text, offer_amount="10.00", confirm=True).json()
    assert body["status"] == "SUBMITTED"
    offer = MockPayPalClient().get_dispute(case.dispute.paypal_dispute_id)["offer"]["seller_offered_amount"]
    assert offer == {"currency_code": "USD", "value": "10.00"}


# Finding 13: other shops' disputes never appear in this shop's evidence
def test_buyer_history_is_this_shop_only(case):
    other = Order.objects.exclude(pk=case.dispute.order_id).first()
    from core.models import Seller
    shop2 = Seller.objects.create(name="Other shop", paypal_merchant_id="OTHER01")
    Order.objects.filter(pk=other.pk).update(seller=shop2, buyer=case.dispute.order.buyer)
    Dispute.objects.create(paypal_dispute_id="PP-D-OTHER", order=other, reason="X", status="RESOLVED",
                           outcome="RESOLVED_BUYER_FAVOUR", amount=Decimal("5"), currency="USD",
                           created_at=case.dispute.created_at, updated_at=case.dispute.created_at)
    ev, _ = evidence.gather(case.dispute)
    assert not any("won" in e["detail"] for e in ev)


# Finding 14: Seller Protection must cover THIS claim's category
def test_protection_category_must_match_reason(case):
    cap = case.dispute.capture
    cap.seller_protection_categories = ["ITEM_NOT_RECEIVED"]
    cap.save()
    Dispute.objects.filter(pk=case.dispute_id).update(reason="UNAUTHORISED")
    case.dispute.refresh_from_db()
    ev, _ = evidence.gather(case.dispute)
    prot = next(e for e in ev if e["kind"] == "seller_protection")
    assert prot["supports"] == "" and prot["data"]["covers_this_claim"] is False


# Finding 16: dates in the seller's time zone
def test_dates_use_seller_timezone(case):
    from datetime import datetime, timezone
    from core.models import Shipment
    Shipment.objects.filter(order=case.dispute.order).update(delivered_at=datetime(2026, 11, 11, 3, 30, tzinfo=timezone.utc))
    ev, _ = evidence.gather(case.dispute)
    assert "10 Nov 2026" in next(e for e in ev if e["kind"] == "delivery")["detail"]  # 21:30 in Austin
