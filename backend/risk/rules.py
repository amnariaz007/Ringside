"""
Deterministic, explainable risk rules.

Every rule is a pure function: (OrderFacts, RiskContext) -> Optional[RuleHit].
No database, no network, no randomness, so each one is trivial to unit test
and the same order always gets the same score.

Thresholds live in constants at the top so they are easy to tune and to quote
in the README.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Callable, Optional

# --- Tunable thresholds -------------------------------------------------------
UNUSUAL_AMOUNT_MULTIPLIER = Decimal("4")     # amount >= 4x the shop's median order
UNUSUAL_AMOUNT_MIN_HISTORY = 10              # need this many past orders for a baseline
VELOCITY_WINDOW_MINUTES = 10
VELOCITY_MIN_ORDERS = 3                      # orders to one address (incl. this one) in the window
REFUND_HABIT_LOOKBACK = 5                    # look at the buyer's last N orders
REFUND_HABIT_MIN_REFUNDS = 2
PRIOR_DISPUTES_DAYS = 60
PRIOR_DISPUTES_MIN = 2
LINKED_BAD_ACTOR_MIN = 2                     # linked accounts with refund/dispute history

PROTECTED_STATUSES = {"ELIGIBLE", "PARTIALLY_ELIGIBLE"}

# Address and phone are strong links. An email pattern alone is weak: two
# honest customers called Emma Garcia share one. It still shows in the
# evidence and the graph, but never counts as a link on its own.
STRONG_LINKS = frozenset({"address", "phone"})


@dataclass(frozen=True)
class OrderFacts:
    """What we know about the order itself. Built from PayPal data."""

    order_id: str
    amount: Decimal
    currency: str
    created_at: datetime
    payer_country: str = ""
    ship_country: str = ""
    seller_protection_status: str = ""   # "" means PayPal didn't tell us
    email_domain: str = ""
    payer_account_status: str = ""       # VERIFIED / UNVERIFIED / ""
    address_is_reshipper: bool = False
    address_text: str = ""


@dataclass(frozen=True)
class LinkedAccount:
    payer_id: str
    link_types: tuple[str, ...]   # any of "address", "phone", "email_pattern"
    refunds: int
    disputes: int


@dataclass(frozen=True)
class RiskContext:
    """History and links, computed from the database before the rules run."""

    shop_median_amount: Optional[Decimal] = None
    shop_order_count: int = 0
    orders_to_address_in_window: int = 1      # includes this order
    new_buyers_to_address_in_window: int = 1
    buyer_recent_order_count: int = 0         # prior orders, up to REFUND_HABIT_LOOKBACK
    buyer_recent_refund_count: int = 0        # refunds among those orders
    buyer_disputes_in_window: int = 0         # disputes in the last PRIOR_DISPUTES_DAYS
    linked_accounts: tuple[LinkedAccount, ...] = field(default_factory=tuple)
    disposable_domains: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class RuleHit:
    rule: str
    points: int
    reason: str
    evidence: dict


Rule = Callable[[OrderFacts, RiskContext], Optional[RuleHit]]


# --- Rules that work on a first order -----------------------------------------

def not_seller_protected(o: OrderFacts, c: RiskContext) -> Optional[RuleHit]:
    if o.seller_protection_status and o.seller_protection_status not in PROTECTED_STATUSES:
        return RuleHit(
            "NOT_SELLER_PROTECTED", 20,
            "Order is not covered by PayPal Seller Protection",
            {"seller_protection_status": o.seller_protection_status},
        )
    return None


def country_mismatch(o: OrderFacts, c: RiskContext) -> Optional[RuleHit]:
    if o.payer_country and o.ship_country and o.payer_country != o.ship_country:
        return RuleHit(
            "COUNTRY_MISMATCH", 15,
            f"Payer country {o.payer_country}, shipping country {o.ship_country}",
            {"payer_country": o.payer_country, "ship_country": o.ship_country},
        )
    return None


def reshipper_address(o: OrderFacts, c: RiskContext) -> Optional[RuleHit]:
    if o.address_is_reshipper:
        return RuleHit(
            "RESHIPPER_ADDRESS", 20,
            "Shipping address matches a known freight-forwarder / reshipper",
            {"address": o.address_text},
        )
    return None


def unusual_amount(o: OrderFacts, c: RiskContext) -> Optional[RuleHit]:
    if (
        c.shop_median_amount
        and c.shop_order_count >= UNUSUAL_AMOUNT_MIN_HISTORY
        and o.amount >= c.shop_median_amount * UNUSUAL_AMOUNT_MULTIPLIER
    ):
        ratio = (o.amount / c.shop_median_amount).quantize(Decimal("0.1"))
        return RuleHit(
            "UNUSUAL_AMOUNT", 15,
            f"{o.currency} {o.amount} is {ratio}x this shop's typical {o.currency} {c.shop_median_amount} order",
            {"amount": str(o.amount), "shop_median": str(c.shop_median_amount), "ratio": str(ratio)},
        )
    return None


def velocity(o: OrderFacts, c: RiskContext) -> Optional[RuleHit]:
    if c.orders_to_address_in_window >= VELOCITY_MIN_ORDERS:
        return RuleHit(
            "VELOCITY", 20,
            f"{c.orders_to_address_in_window} orders to one address in {VELOCITY_WINDOW_MINUTES} minutes"
            f" ({c.new_buyers_to_address_in_window} from new buyers)",
            {
                "orders_in_window": c.orders_to_address_in_window,
                "new_buyers_in_window": c.new_buyers_to_address_in_window,
                "window_minutes": VELOCITY_WINDOW_MINUTES,
            },
        )
    return None


def disposable_email(o: OrderFacts, c: RiskContext) -> Optional[RuleHit]:
    if o.email_domain and o.email_domain in c.disposable_domains:
        return RuleHit(
            "DISPOSABLE_EMAIL", 10,
            f"Email domain {o.email_domain} is a disposable-email service",
            {"email_domain": o.email_domain},
        )
    return None


def unverified_payer(o: OrderFacts, c: RiskContext) -> Optional[RuleHit]:
    if o.payer_account_status == "UNVERIFIED":
        return RuleHit(
            "UNVERIFIED_PAYER", 10,
            "Payer's PayPal account is not verified",
            {"account_status": o.payer_account_status},
        )
    return None


# --- Rules that need history or links -----------------------------------------

def refund_habit(o: OrderFacts, c: RiskContext) -> Optional[RuleHit]:
    if c.buyer_recent_refund_count >= REFUND_HABIT_MIN_REFUNDS:
        return RuleHit(
            "REFUND_HABIT", 25,
            f"{c.buyer_recent_refund_count} refunds in this buyer's last {c.buyer_recent_order_count} orders",
            {"refunds": c.buyer_recent_refund_count, "orders": c.buyer_recent_order_count},
        )
    return None


def prior_disputes(o: OrderFacts, c: RiskContext) -> Optional[RuleHit]:
    if c.buyer_disputes_in_window >= PRIOR_DISPUTES_MIN:
        return RuleHit(
            "PRIOR_DISPUTES", 30,
            f"{c.buyer_disputes_in_window} disputes filed in the last {PRIOR_DISPUTES_DAYS} days",
            {"disputes": c.buyer_disputes_in_window, "days": PRIOR_DISPUTES_DAYS},
        )
    return None


def linked_to_bad_actor(o: OrderFacts, c: RiskContext) -> Optional[RuleHit]:
    bad = [a for a in c.linked_accounts if (a.refunds or a.disputes) and STRONG_LINKS & set(a.link_types)]
    if len(bad) >= LINKED_BAD_ACTOR_MIN:
        link_types = sorted({t for a in bad for t in a.link_types})
        return RuleHit(
            "LINKED_TO_BAD_ACTOR", 35,
            f"Shares {' / '.join(t.replace('_', ' ') for t in link_types)} with {len(bad)} accounts"
            " that refunded or disputed",
            {
                "linked_accounts": [
                    {"payer_id": a.payer_id, "links": list(a.link_types), "refunds": a.refunds, "disputes": a.disputes}
                    for a in bad
                ]
            },
        )
    return None


ALL_RULES: tuple[Rule, ...] = (
    not_seller_protected,
    country_mismatch,
    reshipper_address,
    unusual_amount,
    velocity,
    disposable_email,
    unverified_payer,
    refund_habit,
    prior_disputes,
    linked_to_bad_actor,
)
# NETWORK_FLAG (F9, stretch) will be added when the simulated seller network exists.


def level_for(score: int) -> str:
    if score >= 60:
        return "high"
    if score >= 30:
        return "medium"
    return "low"


def evaluate(o: OrderFacts, c: RiskContext, rules: tuple[Rule, ...] = ALL_RULES) -> tuple[int, str, list[RuleHit]]:
    hits = [h for h in (rule(o, c) for rule in rules) if h is not None]
    score = min(100, sum(h.points for h in hits))
    return score, level_for(score), sorted(hits, key=lambda h: -h.points)
