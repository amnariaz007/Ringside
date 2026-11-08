"""
The dispute copilot pipeline.

    prepare(dispute)      gather evidence -> recommend (rules) -> draft (AI, checked) -> READY
    submit(case, ...)     only after a seller approves: send to PayPal -> SUBMITTED -> refresh

Each step is its own function and saves its result, so the Render Workflow can
run them as separate tasks with their own retries. Today they run inline
(COPILOT_RUNNER=inline).

State machine (DisputeCase.status):
    PREPARING -> READY -> SUBMITTING -> SUBMITTED
                   ^          |
                   |          v
                 (force)    FAILED -> (retry) SUBMITTING
    NEEDS_DATA: the dispute isn't linked to an order yet; prepared again when it is.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from ai.providers import get_provider
from audit.models import record
from core.models import Dispute
from paypal_integration.client import get_client, other_evidence, proof_of_fulfillment
from paypal_integration.ingest import ingest_dispute

from . import evidence as evidence_step
from . import guard, recommend
from .models import DisputeCase

ACTIONS = {"FIGHT", "ACCEPT", "PARTIAL_REFUND"}
WAITING = "WAITING_FOR_SELLER_RESPONSE"


class CopilotError(Exception):
    """A seller request that can't be done (wrong state, bad input)."""


# --- prepare --------------------------------------------------------------------------

def step_gather(case: DisputeCase) -> DisputeCase:
    case.evidence, case.buyer_messages = evidence_step.gather(case.dispute)
    case.save(update_fields=["evidence", "buyer_messages", "updated_at"])
    record("system", "copilot.evidence_gathered", obj=case, paypal_id=case.dispute.paypal_dispute_id,
           evidence_ids=[e["id"] for e in case.evidence], buyer_messages=len(case.buyer_messages))
    return case


def step_recommend(case: DisputeCase) -> DisputeCase:
    d = case.dispute
    rec = recommend.decide(d.reason, d.amount, case.evidence, d.currency)
    case.recommendation, case.confidence, case.reasons = rec.action, rec.confidence, rec.reasons
    # Always keep a suggested partial offer, so a seller can choose it even when it isn't recommended.
    case.offer_amount = rec.offer_amount or recommend.suggested_offer(d.amount, d.currency)
    case.save(update_fields=["recommendation", "confidence", "reasons", "offer_amount", "updated_at"])
    record("system", "copilot.recommended", obj=case, paypal_id=d.paypal_dispute_id,
           recommendation=rec.action, confidence=rec.confidence)
    return case


def step_draft(case: DisputeCase) -> DisputeCase:
    d = case.dispute
    offer = case.offer_amount if case.recommendation == "PARTIAL_REFUND" else None
    result = get_provider().draft_dispute(
        action=case.recommendation, reason=d.reason, evidence=guard.shareable(case.evidence),
        buyer_messages=case.buyer_messages, offer_amount=offer, currency=d.currency,
    )
    # Belt and braces: even the template draft must pass the same check.
    problems = guard.check(result.text, case.recommendation, case.evidence, offer_amount=offer, currency=d.currency)
    if problems:
        raise RuntimeError(f"draft failed checks after fallback: {problems}")
    fields = dict(draft_text=result.text, draft_source=result.source, draft_cited=list(result.cited),
                  guard_notes=list(result.notes), status="READY", prepared_at=timezone.now())
    # Only finish if nobody started submitting meanwhile (a regenerate racing a submit).
    if not DisputeCase.objects.filter(pk=case.pk, status="PREPARING").update(**fields, updated_at=timezone.now()):
        case.refresh_from_db()
        return case
    for k, v in fields.items():
        setattr(case, k, v)
    if result.notes:
        record("ai", "copilot.ai_draft_rejected", obj=case, paypal_id=d.paypal_dispute_id, notes=list(result.notes))
    record("ai", "copilot.draft_created", obj=case, paypal_id=d.paypal_dispute_id,
           source=result.source, cited=list(result.cited))
    return case


def prepare(dispute: Dispute, *, force: bool = False) -> DisputeCase:
    """
    Run the prepare steps. Idempotent: READY and FAILED cases are left alone
    unless force=True; submitted cases are never touched.
    """
    with transaction.atomic():
        case, _ = DisputeCase.objects.select_for_update().get_or_create(dispute=dispute)
        if case.status in {"SUBMITTING", "SUBMITTED"}:
            return case
        if case.status in {"READY", "FAILED"} and not force:
            return case
        if dispute.order_id is None:
            # No order means no evidence: don't guess a recommendation.
            case.status, case.evidence, case.recommendation = "NEEDS_DATA", [], ""
            case.save(update_fields=["status", "evidence", "recommendation", "updated_at"])
            record("system", "copilot.needs_data", obj=case, paypal_id=dispute.paypal_dispute_id,
                   reason="dispute is not linked to a known order yet")
            return case
        case.status = "PREPARING"
        case.save(update_fields=["status", "updated_at"])
    for step in (step_gather, step_recommend, step_draft):
        case = step(case)
    return case


# --- submit (seller-approved only) ----------------------------------------------------

def _offer(case: DisputeCase, requested) -> Decimal:
    d = case.dispute
    value = case.offer_amount if requested in (None, "") else requested
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise CopilotError("offer amount must be a number")
    unit = recommend.minor_unit(d.currency)
    if amount != amount.quantize(unit):
        raise CopilotError(f"{d.currency} offers must be in steps of {unit}")
    if not Decimal("0") < amount < d.amount:
        raise CopilotError(f"a partial refund must be more than 0 and less than {d.currency} {d.amount}")
    return amount


def submit(case: DisputeCase, *, action: str, text: str, offer_amount=None) -> DisputeCase:
    """Send the seller's approved response to PayPal. Never called without a seller click."""
    if action not in ACTIONS:
        raise CopilotError(f"unknown action {action!r}")
    text = text.strip()
    if not 20 <= len(text) <= guard.MAX_CHARS:
        raise CopilotError(f"response must be 20 to {guard.MAX_CHARS} characters")
    client = get_client()

    with transaction.atomic():
        case = DisputeCase.objects.select_for_update().select_related("dispute").get(pk=case.pk)
        dispute = case.dispute
        if case.status not in {"READY", "FAILED"}:
            raise CopilotError(f"case is {case.status.lower()}; it can't be submitted now")
        offer = _offer(case, offer_amount) if action == "PARTIAL_REFUND" else None
        if case.status == "FAILED":
            # The last attempt may have reached PayPal before failing. Check before sending again.
            try:
                live, _ = ingest_dispute(client.get_dispute(dispute.paypal_dispute_id))
                dispute.refresh_from_db()
            except Exception as exc:
                raise CopilotError(f"couldn't confirm the dispute's status with PayPal: {exc}") from exc
            if dispute.status != WAITING:
                case.status, case.submitted_at, case.error = "SUBMITTED", case.submitted_at or timezone.now(), ""
                case.save(update_fields=["status", "submitted_at", "error", "updated_at"])
                record("system", "copilot.reconciled", obj=case, paypal_id=dispute.paypal_dispute_id,
                       paypal_status=dispute.status)
                return case
        if dispute.status != WAITING:
            raise CopilotError(f"PayPal dispute is {dispute.status}, not waiting for the seller")
        case.status = "SUBMITTING"
        case.decided_action, case.final_text = action, text
        if offer is not None:
            case.offer_amount = offer
        case.edited_by_seller = text != case.draft_text.strip() or action != case.recommendation
        case.approved_at = timezone.now()
        case.save()

    record("seller", "copilot.approved", obj=case, paypal_id=dispute.paypal_dispute_id, decision=action,
           followed_recommendation=action == case.recommendation, edited=case.edited_by_seller,
           offer=str(offer) if offer is not None else "")

    note = guard.strip_citations(text)
    try:
        if action == "FIGHT":
            tracking = next((e for e in case.evidence if e["kind"] == "tracking" and e["data"].get("tracking_number")), None)
            evidences = ([proof_of_fulfillment(tracking["data"].get("carrier", "OTHER"), tracking["data"]["tracking_number"], note)]
                         if tracking else [other_evidence(note)])
            response = client.provide_evidence(dispute.paypal_dispute_id, evidences)
        elif action == "ACCEPT":
            response = client.accept_claim(dispute.paypal_dispute_id, note)
        else:
            response = client.make_offer(dispute.paypal_dispute_id, str(offer), dispute.currency, note)
    except Exception as exc:  # timeouts, bad JSON, PayPal errors: never leave the case stuck in SUBMITTING
        case.status, case.error = "FAILED", f"{type(exc).__name__}: {exc}"[:1000]
        case.save(update_fields=["status", "error", "updated_at"])
        record("paypal", "copilot.submit_failed", obj=case, paypal_id=dispute.paypal_dispute_id, error=case.error)
        return case

    # PayPal accepted it. Record that first; a failed refresh must never hide a real submission.
    case.status, case.submitted_at, case.paypal_response, case.error = "SUBMITTED", timezone.now(), response or {}, ""
    case.save(update_fields=["status", "submitted_at", "paypal_response", "error", "updated_at"])
    try:
        ingest_dispute(client.get_dispute(dispute.paypal_dispute_id))
        dispute.refresh_from_db()
    except Exception as exc:
        record("system", "copilot.refresh_failed", obj=case, paypal_id=dispute.paypal_dispute_id,
               error=str(exc)[:300], note="submission succeeded; status will update from the next webhook")
    record("paypal", "copilot.submitted", obj=case, paypal_id=dispute.paypal_dispute_id, decision=action,
           paypal_status=dispute.status)
    return case
