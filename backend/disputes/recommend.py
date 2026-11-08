"""
Step 2 of the copilot: recommend fight, accept or partial refund.

This is deterministic rules, not AI. The AI never decides; it only writes
the words. Two safety rules hold for every case:

  * A ring link or risk score alone never produces FIGHT. Without proof of
    shipping, suspicion isn't evidence PayPal will accept.
  * Nothing a buyer writes can change the recommendation (messages aren't inputs).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

INR = "MERCHANDISE_OR_SERVICE_NOT_RECEIVED"
SNAD = "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED"
UNAUTHORISED = "UNAUTHORISED"
PARTIAL_REFUND_SHARE = Decimal("0.30")


@dataclass
class Recommendation:
    action: str          # FIGHT / ACCEPT / PARTIAL_REFUND
    confidence: str      # high / medium / low
    reasons: list[dict] = field(default_factory=list)   # [{text, evidence_ids}]
    offer_amount: Decimal | None = None


def _find(evidence: list[dict], kind: str) -> dict | None:
    return next((e for e in evidence if e["kind"] == kind), None)


def decide(reason: str, amount: Decimal, evidence: list[dict]) -> Recommendation:
    tracking = _find(evidence, "tracking")
    delivery = _find(evidence, "delivery")
    protection = _find(evidence, "seller_protection")
    history = _find(evidence, "buyer_history")
    ring = _find(evidence, "ring")

    shipped = bool(tracking and tracking["data"].get("tracking_number"))
    to_paypal_address = bool(tracking and tracking["data"].get("to_paypal_address"))
    protected = bool(protection and protection["supports"] == "fight")

    def why(text, *items):
        return {"text": text, "evidence_ids": [i["id"] for i in items if i]}

    def extras(rec: Recommendation) -> Recommendation:
        # Supporting context only: these never create a FIGHT on their own.
        if rec.action == "FIGHT" and history and history["data"].get("undisputed_orders"):
            rec.reasons.append(why("The buyer has completed earlier orders with you without complaint.", history))
        if rec.action == "FIGHT" and ring:
            rec.reasons.append(why("The buyer is linked to accounts that refunded or disputed before; "
                                   "keep this as context, not as proof.", ring))
        return rec

    if reason in (INR, UNAUTHORISED):
        if shipped and delivery and to_paypal_address:
            rec = Recommendation("FIGHT", "high" if protected else "medium", [
                why("Tracking shows the order was delivered to the address on the PayPal transaction.", tracking, delivery)])
            if protected:
                rec.reasons.append(why("The sale is covered by PayPal Seller Protection.", protection))
            else:
                rec.reasons.append(why("The sale is not covered by Seller Protection, so PayPal may still side with the buyer.", protection))
            return extras(rec)
        if shipped and delivery:
            return extras(Recommendation("FIGHT", "low", [
                why("Tracking shows delivery, but to an address other than the one on the PayPal transaction, "
                    "which weakens Seller Protection.", tracking, delivery)]))
        if shipped:
            return extras(Recommendation("FIGHT", "low", [
                why("The order shipped with tracking, but delivery isn't confirmed yet. Send the tracking and "
                    "check the carrier before the deadline.", tracking)]))
        return Recommendation("ACCEPT", "medium", [
            why("There is no tracking or proof of delivery, so PayPal will almost certainly side with the buyer. "
                "Accepting now avoids a claim escalation.", tracking)])

    if reason == SNAD:
        offer = (amount * PARTIAL_REFUND_SHARE).quantize(Decimal("0.01"), ROUND_HALF_UP)
        return Recommendation("PARTIAL_REFUND", "medium", [
            why(f"For 'not as described' claims, a partial refund ({int(PARTIAL_REFUND_SHARE * 100)}%) often settles "
                "the case faster than a return. The buyer must agree to it.")], offer_amount=offer)

    return Recommendation("ACCEPT", "low", [
        why(f"Ringside has no rule for the reason '{reason.replace('_', ' ').lower()}'. Review the case yourself "
            "before choosing.")])
