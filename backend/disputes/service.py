"""
The dispute copilot pipeline.

    prepare(dispute)      gather evidence -> recommend (rules) -> draft (AI, checked) -> READY
    submit(case, ...)     only after a seller approves: send to PayPal -> re-fetch -> SUBMITTED

Each step is its own function and saves its result, so the Render Workflow
(day 3) can run them as separate tasks with their own retries. Today they run
inline (COPILOT_RUNNER=inline).
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from ai.providers import get_provider
from audit.models import record
from core.models import Dispute
from paypal_integration.client import PayPalError, get_client, other_evidence, proof_of_fulfillment
from paypal_integration.ingest import ingest_dispute

from . import evidence as evidence_step
from . import guard, recommend
from .models import DisputeCase

ACTIONS = {"FIGHT", "ACCEPT", "PARTIAL_REFUND"}


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
    rec = recommend.decide(case.dispute.reason, case.dispute.amount, case.evidence)
    case.recommendation, case.confidence, case.reasons = rec.action, rec.confidence, rec.reasons
    case.offer_amount = rec.offer_amount
    case.save(update_fields=["recommendation", "confidence", "reasons", "offer_amount", "updated_at"])
    record("system", "copilot.recommended", obj=case, paypal_id=case.dispute.paypal_dispute_id,
           recommendation=rec.action, confidence=rec.confidence)
    return case


def step_draft(case: DisputeCase) -> DisputeCase:
    result = get_provider().draft_dispute(
        action=case.recommendation, reason=case.dispute.reason, evidence=case.evidence,
        buyer_messages=case.buyer_messages, offer_amount=case.offer_amount, currency=case.dispute.currency,
    )
    # Belt and braces: even the template draft must pass the same check.
    problems = guard.check(result.text, case.recommendation, case.evidence)
    if problems:
        raise RuntimeError(f"draft failed checks after fallback: {problems}")
    case.draft_text, case.draft_source = result.text, result.source
    case.draft_cited, case.guard_notes = list(result.cited), list(result.notes)
    case.status, case.prepared_at = "READY", timezone.now()
    case.save(update_fields=["draft_text", "draft_source", "draft_cited", "guard_notes", "status",
                             "prepared_at", "updated_at"])
    if result.notes:
        record("ai", "copilot.ai_draft_rejected", obj=case, paypal_id=case.dispute.paypal_dispute_id,
               notes=list(result.notes))
    record("ai", "copilot.draft_created", obj=case, paypal_id=case.dispute.paypal_dispute_id,
           source=result.source, cited=list(result.cited), text=result.text)
    return case


def prepare(dispute: Dispute, *, force: bool = False) -> DisputeCase:
    """Run all prepare steps. Idempotent: a READY case is left alone unless force=True."""
    case, created = DisputeCase.objects.get_or_create(dispute=dispute)
    if case.status in {"SUBMITTING", "SUBMITTED"}:
        return case
    if case.status == "READY" and not force:
        return case
    case.status = "PREPARING"
    case.save(update_fields=["status", "updated_at"])
    for step in (step_gather, step_recommend, step_draft):
        case = step(case)
    return case


# --- submit (seller-approved only) ----------------------------------------------------

def submit(case: DisputeCase, *, action: str, text: str) -> DisputeCase:
    """Send the seller's approved response to PayPal. Never called without a seller click."""
    if action not in ACTIONS:
        raise CopilotError(f"unknown action {action!r}")
    text = text.strip()
    if not 20 <= len(text) <= guard.MAX_CHARS:
        raise CopilotError(f"response must be 20 to {guard.MAX_CHARS} characters")

    with transaction.atomic():
        case = DisputeCase.objects.select_for_update().select_related("dispute").get(pk=case.pk)
        if case.status not in {"READY", "FAILED"}:
            raise CopilotError(f"case is {case.status.lower()}; it can't be submitted now")
        if case.dispute.status != "WAITING_FOR_SELLER_RESPONSE":
            raise CopilotError(f"PayPal dispute is {case.dispute.status}, not waiting for the seller")
        if action == "PARTIAL_REFUND" and not case.offer_amount:
            raise CopilotError("no offer amount for a partial refund")
        case.status = "SUBMITTING"
        case.decided_action, case.final_text = action, text
        case.edited_by_seller = text != case.draft_text.strip() or action != case.recommendation
        case.approved_at = timezone.now()
        case.save()

    dispute = case.dispute
    record("seller", "copilot.approved", obj=case, paypal_id=dispute.paypal_dispute_id, decision=action,
           followed_recommendation=action == case.recommendation, edited=case.edited_by_seller)

    note = guard.strip_citations(text)
    client = get_client()
    try:
        if action == "FIGHT":
            tracking = next((e for e in case.evidence if e["kind"] == "tracking" and e["data"].get("tracking_number")), None)
            evidences = ([proof_of_fulfillment(tracking["data"]["carrier"], tracking["data"]["tracking_number"], note)]
                         if tracking else [other_evidence(note)])
            response = client.provide_evidence(dispute.paypal_dispute_id, evidences)
        elif action == "ACCEPT":
            response = client.accept_claim(dispute.paypal_dispute_id, note)
        else:
            response = client.make_offer(dispute.paypal_dispute_id, str(Decimal(case.offer_amount)),
                                         dispute.currency, note)
    except PayPalError as exc:
        case.status, case.error = "FAILED", str(exc)[:1000]
        case.save(update_fields=["status", "error", "updated_at"])
        record("paypal", "copilot.submit_failed", obj=case, paypal_id=dispute.paypal_dispute_id, error=case.error)
        return case

    # PayPal's response only has links; re-fetch the dispute so our status matches theirs.
    ingest_dispute(client.get_dispute(dispute.paypal_dispute_id))
    case.status, case.submitted_at, case.paypal_response, case.error = "SUBMITTED", timezone.now(), response, ""
    case.save(update_fields=["status", "submitted_at", "paypal_response", "error", "updated_at"])
    dispute.refresh_from_db()
    record("paypal", "copilot.submitted", obj=case, paypal_id=dispute.paypal_dispute_id, decision=action,
           paypal_status=dispute.status)
    return case
