from django.db.models import Prefetch
from rest_framework import serializers, viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response

from audit.models import AuditEvent
from risk.models import RiskAssessment

from . import dashboard
from .models import Dispute, Order
from .serializers import DisputeSerializer, OrderDetailSerializer, OrderListSerializer


class OrderViewSet(viewsets.ReadOnlyModelViewSet):
    """Orders with their latest risk score. ?level=high filters by risk level."""

    def get_queryset(self):
        qs = Order.objects.select_related("buyer", "shipping_address").prefetch_related(
            "captures__refunds",
            "disputes",
            Prefetch("assessments", queryset=RiskAssessment.objects.prefetch_related("findings")),
        )
        level = self.request.query_params.get("level")
        if level:
            # Filter on the latest assessment, the one each row displays.
            qs = dashboard.with_latest_assessment(qs).filter(latest_level=level)
        return qs

    def get_serializer_class(self):
        return OrderDetailSerializer if self.action == "retrieve" else OrderListSerializer


class DisputeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Dispute.objects.select_related("order__buyer", "case")
    serializer_class = DisputeSerializer


@api_view(["GET"])
def dashboard_view(request):
    return Response(dashboard.summary())


class AuditEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditEvent
        fields = ["id", "actor", "action", "object_type", "object_id", "paypal_id", "payload", "created_at"]


class AuditEventViewSet(viewsets.ReadOnlyModelViewSet):
    """Append-only audit trail. Filter with ?actor=ai or ?paypal_id=<id>."""

    serializer_class = AuditEventSerializer

    def get_queryset(self):
        qs = AuditEvent.objects.all()
        for field in ("actor", "paypal_id", "action"):
            value = self.request.query_params.get(field)
            if value:
                qs = qs.filter(**{field: value})
        return qs
