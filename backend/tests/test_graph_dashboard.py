"""Day 2: fraud-ring graph, dashboard metrics, audit API, Seller Protection advice."""

import pytest

from ai.providers import TemplateProvider, _join
from paypal_integration import demo

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded():
    demo.seed_history()
    for name in ("normal", "scammer", "ring", "dispute"):
        demo.live_scenario(name)


def test_only_the_real_ring_is_detected(seeded, client):
    rings = client.get("/api/graph/rings/").json()["results"]
    assert [r["payer_ids"] for r in rings] == [["RINGPAYER0001", "RINGPAYER0002", "RINGPAYER0003", "RINGPAYER0004"]]


def test_same_name_customers_are_not_a_ring(client):
    # Two honest "Emma Garcia"s share an email stem (emmagarcia@gmail.com) but no address or phone.
    from datetime import datetime, timezone
    from paypal_integration import payloads
    from paypal_integration.ingest import ingest_order
    demo.get_or_create_seller()
    at = datetime(2026, 11, 1, tzinfo=timezone.utc)
    for i, (email, street, phone) in enumerate([("emma.garcia12@gmail.com", "12 Oak St", "5125550001"),
                                                 ("emmagarcia.88@gmail.com", "77 Pine Ave", "3035550002")]):
        ingest_order(payloads.order(merchant_id=demo.MERCHANT_ID, payer_id=f"EMMA{i}", email=email,
                                    given_name="Emma", surname="Garcia", payer_country="US", amount="40.00",
                                    created_at=at, ship_line1=street, ship_city="Austin", ship_postal="78701",
                                    ship_country="US", phone=phone))
    assert client.get("/api/graph/rings/").json()["results"] == []
    g = client.get("/api/graph/buyers/EMMA1/").json()
    assert g["is_ring"] is False and {n["type"] for n in g["nodes"]} == {"buyer", "order", "address"}


def test_ring_stats_and_summary(seeded, client):
    ring = client.get("/api/graph/rings/").json()["results"][0]
    s = ring["stats"]
    assert (s["buyers"], s["orders"], s["refunds"], s["disputes_lost"]) == (4, 4, 2, 1)
    assert (s["shared_addresses"], s["shared_phones"], s["shared_email_patterns"]) == (1, 2, 1)
    assert s["open_high_risk_amount"] == "89.00"
    assert ring["summary"].startswith("4 accounts share 1 shipping address, 2 phone numbers and 1 email pattern")
    assert ring["summary_source"] == "template"


def test_buyer_graph_shape_is_react_flow_ready(seeded, client):
    g = client.get("/api/graph/buyers/RINGPAYER0004/").json()
    ids = {n["id"] for n in g["nodes"]}
    assert len(ids) == len(g["nodes"])  # unique node ids
    assert all(e["source"] in ids and e["target"] in ids for e in g["edges"])  # no dangling edges
    types = {n["type"] for n in g["nodes"]}
    assert types == {"buyer", "order", "address", "phone", "email_pattern", "refund", "dispute"}
    buyer4 = next(n for n in g["nodes"] if n["id"] == "buyer:RINGPAYER0004")
    assert buyer4["data"]["level"] == "high" and buyer4["data"]["max_score"] == 70


def test_graph_never_exposes_raw_contact_details(seeded, client):
    body = client.get("/api/graph/buyers/RINGPAYER0004/").content.decode()
    assert "2015550101" not in body and "sana.m1" not in body


def test_unknown_buyer_graph_is_404(client):
    assert client.get("/api/graph/buyers/NOPE/").status_code == 404


def test_dashboard_numbers(seeded, client):
    d = client.get("/api/dashboard/").json()
    assert d["level_counts"] == {"low": 63, "medium": 1, "high": 2}
    # Scammer $480 + ring account 4 $89; ring account 3 (medium) was later disputed, so not "at risk".
    assert d["money_at_risk"]["risky_orders_amount"] == "569.00"
    assert d["money_at_risk"]["risky_orders_count"] == 2
    assert d["dispute_record"] == {"won": 0, "lost": 1, "other": 0}
    assert len(d["open_disputes"]) == 1 and d["open_disputes"][0]["hours_left"] > 0
    assert d["riskiest_buyers"][0]["payer_id"] == "SCAMPAYER0001"


def test_order_detail_has_advice_refunds_and_disputes(seeded, client):
    from core.models import Order
    scam = Order.objects.get(buyer__payer_id="SCAMPAYER0001")
    body = client.get(f"/api/orders/{scam.pk}/").json()
    assert body["is_reshipper"] is True
    assert body["seller_protection_advice"].startswith("Not covered")
    ring1 = Order.objects.get(buyer__payer_id="RINGPAYER0001")
    assert len(client.get(f"/api/orders/{ring1.pk}/").json()["refunds"]) == 1


def test_audit_api_filters_by_actor(seeded, client):
    rows = client.get("/api/audit/?actor=ai").json()["results"]
    assert rows and all(r["actor"] == "ai" for r in rows)
    assert "risk.explained" in {r["action"] for r in rows}


def test_single_buyer_summary_wording():
    text = TemplateProvider().summarize_ring({"buyers": 1, "refunds": 0, "disputes": 0,
                                              "open_high_risk_amount": "480.00"}).text
    assert text == ("Not linked to any other account by shipping address or phone. "
                    "USD 480.00 in high-risk orders is still unshipped or unresolved: review before fulfilling.")


@pytest.mark.parametrize("items,out", [([], ""), (["a"], "a"), (["a", "b"], "a and b"), (["a", "b", "c"], "a, b and c")])
def test_join(items, out):
    assert _join(items) == out
