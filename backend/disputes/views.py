from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.response import Response

from core.models import Dispute

from . import service
from .models import DisputeCase


class CaseSerializer(serializers.ModelSerializer):
    dispute = serializers.SerializerMethodField()

    class Meta:
        model = DisputeCase
        fields = [
            "id", "status", "dispute", "evidence", "buyer_messages", "recommendation", "confidence", "reasons",
            "offer_amount", "draft_text", "draft_source", "draft_cited", "guard_notes", "decided_action",
            "final_text", "edited_by_seller", "approved_at", "submitted_at", "error", "prepared_at",
        ]

    def get_dispute(self, case):
        d = case.dispute
        return {
            "id": d.pk, "paypal_dispute_id": d.paypal_dispute_id, "reason": d.reason, "status": d.status,
            "amount": str(d.amount), "currency": d.currency, "outcome": d.outcome,
            "seller_response_due_at": d.seller_response_due_at, "created_at": d.created_at,
            "order_id": d.order_id, "paypal_order_id": d.order.paypal_order_id if d.order else "",
            "awaiting_seller": d.status == "WAITING_FOR_SELLER_RESPONSE",
            "buyer": str(d.order.buyer) if d.order else "", "payer_id": d.order.buyer.payer_id if d.order else "",
        }


def _dispute(pk):
    return Dispute.objects.select_related("order__buyer", "capture").filter(pk=pk).first()


@api_view(["GET"])
def case_detail(request, pk: int):
    """The copilot case for a dispute; prepared on first view if the webhook didn't already."""
    dispute = _dispute(pk)
    if dispute is None:
        return Response({"detail": "dispute not found"}, status=404)
    case = service.prepare(dispute)
    return Response(CaseSerializer(case).data)


@api_view(["POST"])
def case_regenerate(request, pk: int):
    dispute = _dispute(pk)
    if dispute is None:
        return Response({"detail": "dispute not found"}, status=404)
    case = getattr(dispute, "case", None)
    if case and case.status in {"SUBMITTING", "SUBMITTED"}:
        return Response({"detail": "already submitted to PayPal"}, status=409)
    return Response(CaseSerializer(service.prepare(dispute, force=True)).data)


@api_view(["POST"])
def case_submit(request, pk: int):
    """Seller approval. Body: {"action": "FIGHT"|"ACCEPT"|"PARTIAL_REFUND", "text": "...", "confirm": true}"""
    dispute = _dispute(pk)
    case = getattr(dispute, "case", None) if dispute else None
    if case is None:
        return Response({"detail": "no copilot case for this dispute"}, status=404)
    if request.data.get("confirm") is not True:
        return Response({"detail": "confirm must be true: nothing is sent to PayPal without explicit approval"},
                        status=400)
    try:
        case = service.submit(case, action=str(request.data.get("action", "")), text=str(request.data.get("text", "")),
                              offer_amount=request.data.get("offer_amount"))
    except service.CopilotError as exc:
        return Response({"detail": str(exc)}, status=409)
    return Response(CaseSerializer(case).data, status=200 if case.status == "SUBMITTED" else 502)
