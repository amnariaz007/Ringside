"""End-to-end: the demo story produces the scores the pitch promises, and the API exposes them."""

import pytest

from core.models import Dispute
from paypal_integration import demo
from risk.models import RiskAssessment

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded():
    demo.seed_history()
    return {name: demo.live_scenario(name) for name in ("normal", "scammer", "ring", "dispute")}


def latest(payer_id):
    return RiskAssessment.objects.filter(order__buyer__payer_id=payer_id).latest("created_at")


def test_normal_history_is_mostly_low_risk(seeded):
    normal = RiskAssessment.objects.filter(order__buyer__payer_id__startswith="NORMALPAYER")
    assert normal.count() == 60
    assert normal.exclude(level="low").count() == 0


def test_first_time_scammer_is_high_risk_with_reasons(seeded):
    a = latest("SCAMPAYER0001")
    assert a.level == "high" and a.score >= 80
    rules = set(a.findings.values_list("rule", flat=True))
    assert {"NOT_SELLER_PROTECTED", "RESHIPPER_ADDRESS", "UNUSUAL_AMOUNT", "COUNTRY_MISMATCH"} <= rules
    assert "Hold shipment" in a.explanation


def test_fraud_ring_fourth_account_is_linked(seeded):
    a = latest("RINGPAYER0004")
    assert a.level == "high"
    linked = a.findings.get(rule="LINKED_TO_BAD_ACTOR")
    assert len(linked.evidence["linked_accounts"]) == 3


def test_ring_account_three_was_flagged_before_its_dispute(seeded):
    # The story: PayGuard would have warned the seller before account 3 cost them money.
    assert latest("RINGPAYER0003").level in {"medium", "high"}


def test_open_dispute_keeps_buyer_message_as_data(seeded):
    d = Dispute.objects.get(status="WAITING_FOR_SELLER_RESPONSE")
    assert d.seller_response_due_at is not None
    assert "ignore your previous instructions" in d.raw["messages"][0]["content"]


def test_seed_is_deterministic():
    from datetime import datetime, timezone

    from core.models import Address, Buyer, Seller

    def run():
        demo.seed_history(now=datetime(2026, 11, 8, tzinfo=timezone.utc))
        result = sorted(RiskAssessment.objects.values_list("order__buyer__payer_id", "score", "level"))
        Seller.objects.all().delete()  # cascades orders, captures, assessments
        Buyer.objects.all().delete()
        Address.objects.all().delete()
        return result

    first, second = run(), run()
    assert first == second and len(first) == 63


def test_orders_api_filters_high_risk(seeded, client):
    resp = client.get("/api/orders/?level=high")
    assert resp.status_code == 200
    payers = {o["payer_id"] for o in resp.json()["results"]}
    assert payers == {"SCAMPAYER0001", "RINGPAYER0004"}


def test_order_detail_includes_findings(seeded, client):
    order_id = latest("SCAMPAYER0001").order_id
    body = client.get(f"/api/orders/{order_id}/").json()
    assert body["assessment"]["score"] >= 80
    assert body["assessment"]["findings"][0]["points"] == 20
    assert body["seller_protection"] == "NOT_ELIGIBLE"


def test_health_reports_modes(client):
    assert client.get("/api/health/").json() == {"ok": True, "paypal_mode": "mock", "ai_provider": "template"}
