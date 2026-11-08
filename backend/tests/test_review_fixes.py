"""Regression tests for the day-2 code review findings (docs/VERIFICATION.md lists each one)."""

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from core import normalize
from core.models import Dispute, Order
from core.outcomes import result
from paypal_integration import demo, payloads
from paypal_integration.ingest import ingest_dispute, ingest_order, ingest_refund
from risk.engine import score_order
from risk.models import RiskAssessment

pytestmark = pytest.mark.django_db
AT = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)


def order(i, **kw):
    demo.get_or_create_seller()
    base = dict(merchant_id=demo.MERCHANT_ID, payer_id=f"P{i}", email=f"buyer{i}x@gmail.com", given_name="A",
                surname=f"B{i}", payer_country="US", amount="50.00", created_at=AT + timedelta(minutes=i),
                ship_line1=f"{i} Oak St", ship_city="Austin", ship_postal="78701", ship_country="US",
                order_id=f"O{i}", capture_id=f"CAP{i}")
    base.update(kw)
    o, _ = ingest_order(payloads.order(**base))
    return o


# Finding 17: plaintext contact details in stored raw JSON
def test_raw_order_json_has_no_email_or_phone():
    o = order(1, email="secret.person@gmail.com", phone="5125550199")
    raw = json.dumps(Order.objects.get(pk=o.pk).raw)
    assert "secret.person" not in raw and "5125550199" not in raw
    assert o.buyer.email_domain == "gmail.com"  # the hash-derived fields still work


def test_raw_dispute_json_has_no_buyer_email():
    order(1)
    d = payloads.dispute(capture_id="CAP1", amount="50.00", created_at=AT)
    d["disputed_transactions"][0]["buyer"] = {"email": "who@example.com", "name": "Who"}
    dispute, _ = ingest_dispute(d)
    assert "who@example.com" not in json.dumps(Dispute.objects.get(pk=dispute.pk).raw)


# Finding 19: hashes are keyed (HMAC), so they can't be recomputed without the secret
def test_hash_depends_on_secret_key(settings):
    a = normalize.hash_phone("5125550199")
    settings.PII_HASH_SALT = "another-secret"
    assert normalize.hash_phone("5125550199") != a


def test_graph_node_ids_do_not_contain_hashes(client):
    demo.seed_history()
    demo.live_scenario("ring")
    body = client.get("/api/graph/buyers/RINGPAYER0004/").json()
    from core.models import Buyer
    hashes = {b.phone_hash[:8] for b in Buyer.objects.exclude(phone_hash="")}
    assert not any(h in n["id"] for n in body["nodes"] for h in hashes)


# Finding 5: buyers without an email must not share a fake "email pattern"
def test_missing_emails_do_not_link_buyers():
    a = order(1, email="", ship_line1="1 Elm St")
    b = order(2, email="", ship_line1="2 Pine St")
    assert a.buyer.email_stem_hash == "" and b.buyer.email_stem_hash == ""
    from risk.context import risk_context
    assert risk_context(b).linked_accounts == ()


# Finding 1: ?level uses the latest assessment only
def test_level_filter_uses_latest_assessment(client):
    o = order(1)
    score_order(o)  # low
    newer = RiskAssessment.objects.create(order=o, score=80, level="high", engine_version="test")
    assert newer.level == "high"
    high = client.get("/api/orders/?level=high").json()["results"]
    low = client.get("/api/orders/?level=low").json()["results"]
    assert [r["id"] for r in high] == [o.pk] and low == []


# Finding 2: a partial refund leaves the unrefunded remainder at risk
def test_partial_refund_keeps_remainder_at_risk(client):
    o = order(1, amount="480.00")
    RiskAssessment.objects.create(order=o, score=90, level="high", engine_version="test")
    ingest_refund(payloads.refund(capture_id="CAP1", amount="5.00", created_at=AT + timedelta(hours=1)))
    risk = client.get("/api/dashboard/").json()["money_at_risk"]
    assert (risk["risky_orders_amount"], risk["risky_orders_count"]) == ("475.00", 1)


# Finding 3: ACCEPTED (seller paid out) counts as a loss
@pytest.mark.parametrize("code,expected", [
    ("RESOLVED_BUYER_FAVOUR", "lost"), ("ACCEPTED", "lost"), ("RESOLVED_SELLER_FAVOUR", "won"),
    ("CANCELED_BY_BUYER", "won"), ("", ""), ("SOMETHING_NEW", ""),
])
def test_outcome_mapping(code, expected):
    assert result(code) == expected


def test_accepted_claim_is_a_loss_on_the_dashboard(client):
    order(1)
    ingest_dispute(payloads.dispute(capture_id="CAP1", amount="50.00", created_at=AT,
                                    status="RESOLVED", outcome="ACCEPTED"))
    assert client.get("/api/dashboard/").json()["dispute_record"] == {"won": 0, "lost": 1, "other": 0}


# Finding 4: other currencies are never summed into the seller's currency
def test_other_currency_not_added_to_usd(client):
    usd = order(1, amount="100.00")
    gbp = order(2, amount="89.00", currency="GBP")
    for o in (usd, gbp):
        RiskAssessment.objects.create(order=o, score=70, level="high", engine_version="test")
    risk = client.get("/api/dashboard/").json()["money_at_risk"]
    assert risk["risky_orders_amount"] == "100.00" and risk["other_currency_orders"] == 1


# Finding 6/13: graph nodes say "won" for a won dispute
def test_graph_dispute_node_reports_won(client):
    order(1)
    ingest_dispute(payloads.dispute(capture_id="CAP1", amount="50.00", created_at=AT,
                                    status="RESOLVED", outcome="RESOLVED_SELLER_FAVOUR"))
    nodes = client.get("/api/graph/buyers/P1/").json()["nodes"]
    assert next(n for n in nodes if n["type"] == "dispute")["data"]["result"] == "won"


# Finding 14: only shared addresses are marked as strong links
def test_unshared_address_is_not_a_strong_link(client):
    order(1)
    g = client.get("/api/graph/buyers/P1/").json()
    assert next(n for n in g["nodes"] if n["type"] == "address")["data"]["shared"] is False
    assert {e["kind"] for e in g["edges"]} == {"placed", "ships_to"}


# Finding 7: blank PayPal names fall back to the payer id
def test_blank_buyer_name_falls_back_to_payer_id(client):
    o = order(1, given_name="", surname="")
    assert client.get(f"/api/orders/{o.pk}/").json()["buyer"] == "P1"


# Finding 18: production refuses insecure defaults
def test_render_refuses_dev_secrets():
    import subprocess, sys, os
    env = {**os.environ, "RENDER": "true", "DJANGO_SECRET_KEY": "", "PII_HASH_SALT": ""}
    env.pop("DJANGO_SECRET_KEY"); env.pop("PII_HASH_SALT"); env.pop("DJANGO_DEBUG", None)
    proc = subprocess.run([sys.executable, "manage.py", "check"], env=env, capture_output=True, text=True)
    assert proc.returncode != 0 and "DJANGO_SECRET_KEY" in proc.stderr
    env.update(DJANGO_SECRET_KEY="x" * 50, PII_HASH_SALT="y" * 32)
    ok = subprocess.run([sys.executable, "manage.py", "check"], env=env, capture_output=True, text=True)
    assert ok.returncode == 0, ok.stderr
