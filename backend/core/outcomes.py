"""
How PayPal dispute outcome codes map to a win or loss for the seller.

Source: Disputes API v1 dispute_outcome.outcome_code. ACCEPTED means the
seller accepted the claim and paid, so it counts as a loss.
"""

BUYER_WON = frozenset({"RESOLVED_BUYER_FAVOUR", "ACCEPTED", "RESOLVED_WITH_PAYOUT"})
SELLER_WON = frozenset({"RESOLVED_SELLER_FAVOUR", "DENIED", "CANCELED_BY_BUYER"})


def result(outcome: str) -> str:
    """'lost', 'won', or '' when unresolved or unknown."""
    if outcome in BUYER_WON:
        return "lost"
    if outcome in SELLER_WON:
        return "won"
    return ""
