from django.db import models

from core.models import Dispute


class DisputeCase(models.Model):
    """
    The copilot's working file for one dispute: evidence, recommendation, AI
    draft, the seller's decision and what was sent to PayPal.

    Nothing reaches PayPal until a seller approves (status READY -> SUBMITTED).
    """

    STATUS = [
        ("NEEDS_DATA", "Waiting for order data"),
        ("PREPARING", "Preparing"),
        ("READY", "Ready for seller review"),
        ("SUBMITTING", "Submitting to PayPal"),
        ("SUBMITTED", "Submitted to PayPal"),
        ("FAILED", "Submission failed"),
    ]
    ACTIONS = [("FIGHT", "Fight with evidence"), ("ACCEPT", "Accept the claim"),
               ("PARTIAL_REFUND", "Offer a partial refund")]

    dispute = models.OneToOneField(Dispute, on_delete=models.CASCADE, related_name="case")
    status = models.CharField(max_length=20, choices=STATUS, default="PREPARING")

    evidence = models.JSONField(default=list)          # [{id, kind, title, detail, data, untrusted}]
    buyer_messages = models.JSONField(default=list)    # untrusted; shown quarantined, never obeyed
    recommendation = models.CharField(max_length=20, choices=ACTIONS, blank=True)
    confidence = models.CharField(max_length=10, blank=True)   # high / medium / low
    reasons = models.JSONField(default=list)           # [{text, evidence_ids}]
    offer_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    draft_text = models.TextField(blank=True)
    draft_source = models.CharField(max_length=40, blank=True)   # "template" or "gemini:<model>"
    draft_cited = models.JSONField(default=list)
    guard_notes = models.JSONField(default=list)       # why an AI draft was rejected, if it was

    # Seller decision
    decided_action = models.CharField(max_length=20, choices=ACTIONS, blank=True)
    final_text = models.TextField(blank=True)
    edited_by_seller = models.BooleanField(default=False)
    approved_at = models.DateTimeField(null=True, blank=True)

    # PayPal result
    submitted_at = models.DateTimeField(null=True, blank=True)
    paypal_response = models.JSONField(default=dict)
    error = models.TextField(blank=True)

    prepared_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
