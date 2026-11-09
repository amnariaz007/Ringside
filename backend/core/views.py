from django.db.models import Prefetch
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response

from audit.models import AuditEvent
from risk.models import RiskAssessment

from . import dashboard
from .shipping import ShipmentError, record_shipment
from .models import Dispute, Order
from .serializers import DisputeSerializer, OrderDetailSerializer, OrderListSerializer


class OrderViewSet(viewsets.ReadOnlyModelViewSet):
    """Orders with their latest risk score. ?level=high filters by risk level."""

    def get_queryset(self):
        qs = Order.objects.select_related("buyer", "shipping_address", "shipment").prefetch_related(
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
        return OrderDetailSerializer if self.action in ("retrieve", "shipment") else OrderListSerializer

    @action(detail=True, methods=["post"])
    def shipment(self, request, pk=None):
        """Record carrier and tracking (and delivery), and send the tracking to PayPal."""
        order = self.get_object()
        try:
            _, paypal_status = record_shipment(order, request.data if isinstance(request.data, dict) else {})
        except ShipmentError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        fresh = self.get_queryset().get(pk=order.pk)
        return Response({**OrderDetailSerializer(fresh).data, "paypal_tracking": paypal_status})


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
