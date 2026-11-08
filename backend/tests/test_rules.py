"""Pure unit tests for every risk rule: no database needed."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from risk import rules
from risk.rules import LinkedAccount, OrderFacts, RiskContext

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def facts(**kw) -> OrderFacts:
    base = dict(order_id="O1", amount=Decimal("50.00"), currency="USD", created_at=NOW,
                payer_country="US", ship_country="US", seller_protection_status="ELIGIBLE",
                email_domain="gmail.com", payer_account_status="VERIFIED")
    base.update(kw)
    return OrderFacts(**base)


def ctx(**kw) -> RiskContext:
    base = dict(shop_median_amount=Decimal("50.00"), shop_order_count=60,
                disposable_domains=frozenset({"mailinator.com"}))
    base.update(kw)
    return RiskContext(**base)


def test_clean_order_scores_zero():
    score, level, hits = rules.evaluate(facts(), ctx())
    assert (score, level, hits) == (0, "low", [])


@pytest.mark.parametrize("status,hit", [
    ("NOT_ELIGIBLE", True), ("ELIGIBLE", False), ("PARTIALLY_ELIGIBLE", False), ("", False),
])
def test_not_seller_protected(status, hit):
    result = rules.not_seller_protected(facts(seller_protection_status=status), ctx())
    assert (result is not None) == hit
    if hit:
        assert result.points == 20 and result.evidence == {"seller_protection_status": "NOT_ELIGIBLE"}


def test_unknown_protection_is_not_penalised():
    # PayPal didn't tell us: don't guess.
    assert rules.not_seller_protected(facts(seller_protection_status=""), ctx()) is None


@pytest.mark.parametrize("payer,ship,hit", [("PK", "US", True), ("US", "US", False), ("", "US", False), ("PK", "", False)])
def test_country_mismatch(payer, ship, hit):
    result = rules.country_mismatch(facts(payer_country=payer, ship_country=ship), ctx())
    assert (result is not None) == hit
    if hit:
        assert result.reason == "Payer country PK, shipping country US"


def test_reshipper_address():
    assert rules.reshipper_address(facts(address_is_reshipper=True), ctx()).points == 20
    assert rules.reshipper_address(facts(address_is_reshipper=False), ctx()) is None


def test_unusual_amount_triggers_at_4x():
    assert rules.unusual_amount(facts(amount=Decimal("200.00")), ctx()) is not None
    assert rules.unusual_amount(facts(amount=Decimal("199.99")), ctx()) is None


def test_unusual_amount_reason_quotes_ratio():
    hit = rules.unusual_amount(facts(amount=Decimal("480.00")), ctx(shop_median_amount=Decimal("45.00")))
    assert "10.7x" in hit.reason and hit.evidence["shop_median"] == "45.00"


def test_unusual_amount_needs_history():
    assert rules.unusual_amount(facts(amount=Decimal("999")), ctx(shop_order_count=9)) is None
    assert rules.unusual_amount(facts(amount=Decimal("999")), ctx(shop_median_amount=None)) is None


def test_velocity():
    assert rules.velocity(facts(), ctx(orders_to_address_in_window=2)) is None
    hit = rules.velocity(facts(), ctx(orders_to_address_in_window=4, new_buyers_to_address_in_window=4))
    assert hit.points == 20 and "4 orders to one address in 10 minutes" in hit.reason


def test_disposable_email():
    assert rules.disposable_email(facts(email_domain="mailinator.com"), ctx()).points == 10
    assert rules.disposable_email(facts(email_domain="gmail.com"), ctx()) is None


def test_unverified_payer():
    assert rules.unverified_payer(facts(payer_account_status="UNVERIFIED"), ctx()).points == 10
    assert rules.unverified_payer(facts(payer_account_status=""), ctx()) is None


def test_refund_habit():
    assert rules.refund_habit(facts(), ctx(buyer_recent_order_count=4, buyer_recent_refund_count=1)) is None
    hit = rules.refund_habit(facts(), ctx(buyer_recent_order_count=4, buyer_recent_refund_count=3))
    assert hit.points == 25 and hit.reason == "3 refunds in this buyer's last 4 orders"


def test_prior_disputes():
    assert rules.prior_disputes(facts(), ctx(buyer_disputes_in_window=1)) is None
    assert rules.prior_disputes(facts(), ctx(buyer_disputes_in_window=2)).points == 30


def test_linked_to_bad_actor_needs_two_bad_accounts():
    clean = LinkedAccount("B1", ("address",), refunds=0, disputes=0)
    bad1 = LinkedAccount("B2", ("address", "phone"), refunds=1, disputes=0)
    bad2 = LinkedAccount("B3", ("email_pattern", "phone"), refunds=0, disputes=1)
    assert rules.linked_to_bad_actor(facts(), ctx(linked_accounts=(clean, bad1))) is None
    hit = rules.linked_to_bad_actor(facts(), ctx(linked_accounts=(clean, bad1, bad2)))
    assert hit.points == 35
    assert hit.reason == "Shares address / email pattern / phone with 2 accounts that refunded or disputed"
    assert [a["payer_id"] for a in hit.evidence["linked_accounts"]] == ["B2", "B3"]


def test_email_pattern_alone_is_not_a_link():
    # Same-name honest customers share an email stem; that must not brand them a ring.
    weak1 = LinkedAccount("B2", ("email_pattern",), refunds=1, disputes=0)
    weak2 = LinkedAccount("B3", ("email_pattern",), refunds=0, disputes=1)
    assert rules.linked_to_bad_actor(facts(), ctx(linked_accounts=(weak1, weak2))) is None


def test_score_caps_at_100_and_sorts_by_points():
    c = ctx(orders_to_address_in_window=5, buyer_recent_order_count=4, buyer_recent_refund_count=3,
            buyer_disputes_in_window=2,
            linked_accounts=(LinkedAccount("B2", ("address",), 1, 0), LinkedAccount("B3", ("address",), 0, 1)))
    score, level, hits = rules.evaluate(facts(seller_protection_status="NOT_ELIGIBLE"), c)
    assert sum(h.points for h in hits) > 100
    assert (score, level) == (100, "high")
    assert [h.points for h in hits] == sorted((h.points for h in hits), reverse=True)


@pytest.mark.parametrize("score,level", [(0, "low"), (29, "low"), (30, "medium"), (59, "medium"), (60, "high"), (100, "high")])
def test_level_boundaries(score, level):
    assert rules.level_for(score) == level


def test_rules_are_deterministic():
    f, c = facts(seller_protection_status="NOT_ELIGIBLE", payer_country="PK"), ctx()
    assert rules.evaluate(f, c) == rules.evaluate(f, c)
