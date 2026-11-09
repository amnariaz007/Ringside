from rest_framework import serializers

from risk.models import Finding, RiskAssessment

from .models import Dispute, Order


class FindingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Finding
        fields = ["rule", "points", "reason", "evidence"]


class AssessmentSerializer(serializers.ModelSerializer):
    findings = FindingSerializer(many=True, read_only=True)

    class Meta:
        model = RiskAssessment
        fields = ["score", "level", "explanation", "explanation_source", "engine_version", "created_at", "findings"]


class OrderListSerializer(serializers.ModelSerializer):
    buyer = serializers.SerializerMethodField()
    payer_id = serializers.CharField(source="buyer.payer_id")
    ship_country = serializers.CharField(source="shipping_address.country_code", default="")
    score = serializers.SerializerMethodField()
    level = serializers.SerializerMethodField()
    seller_protection = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id", "paypal_order_id", "created_at", "amount", "currency", "buyer", "payer_id",
            "payer_country", "ship_country", "seller_protection", "score", "level", "rules",
        ]

    def get_buyer(self, obj):
        return str(obj.buyer)  # display name, or payer id when PayPal sent no name

    def _latest(self, obj):
        # Uses the prefetched list, so no extra query per row.
        items = list(obj.assessments.all())
        return items[0] if items else None

    def get_score(self, obj):
        a = self._latest(obj)
        return a.score if a else None

    def get_level(self, obj):
        a = self._latest(obj)
        return a.level if a else None

    rules = serializers.SerializerMethodField()

    def get_rules(self, obj):
        """Rule codes behind the latest score, biggest first (uses prefetched findings)."""
        a = self._latest(obj)
        return [f.rule for f in sorted(a.findings.all(), key=lambda f: -f.points)] if a else []

    def get_seller_protection(self, obj):
        caps = list(obj.captures.all())
        return caps[0].seller_protection_status if caps else ""


# What each PayPal Seller Protection status means for the seller, in plain words.
SELLER_PROTECTION_ADVICE = {
    "ELIGIBLE": "Covered for item-not-received and unauthorised-payment claims, as long as you ship to the "
                "address on the PayPal transaction and keep online tracking.",
    "PARTIALLY_ELIGIBLE": "Covered for item-not-received claims only. Ship to the PayPal address with tracking "
                          "that shows delivery.",
    "NOT_ELIGIBLE": "Not covered by Seller Protection. Use tracked shipping with signature on delivery, "
                    "or refund before shipping if the order looks risky.",
    "": "PayPal did not report Seller Protection for this order.",
}


class OrderDetailSerializer(OrderListSerializer):
    assessment = serializers.SerializerMethodField()
    shipping_address = serializers.StringRelatedField()
    seller_protection_advice = serializers.SerializerMethodField()
    is_reshipper = serializers.BooleanField(source="shipping_address.is_reshipper", default=False)
    refunds = serializers.SerializerMethodField()
    disputes = serializers.SerializerMethodField()
    shipment = serializers.SerializerMethodField()
    can_ship = serializers.SerializerMethodField()

    class Meta(OrderListSerializer.Meta):
        fields = OrderListSerializer.Meta.fields + [
            "status", "shipping_address", "is_reshipper", "seller_protection_advice", "assessment",
            "refunds", "disputes", "shipment", "can_ship",
        ]

    def get_shipment(self, obj):
        s = getattr(obj, "shipment", None)
        if s is None:
            return None
        return {"carrier": s.carrier, "tracking_number": s.tracking_number, "status": s.status,
                "shipped_at": s.shipped_at, "delivered_at": s.delivered_at,
                "to_paypal_address": s.to_paypal_address, "signature_confirmed": s.signature_confirmed}

    def get_can_ship(self, obj):
        return any(c.status == "COMPLETED" for c in obj.captures.all())

    def get_seller_protection_advice(self, obj):
        return SELLER_PROTECTION_ADVICE.get(self.get_seller_protection(obj), SELLER_PROTECTION_ADVICE[""])

    def get_refunds(self, obj):
        return [{"paypal_refund_id": r.paypal_refund_id, "amount": str(r.amount), "created_at": r.created_at}
                for c in obj.captures.all() for r in c.refunds.all()]

    def get_disputes(self, obj):
        return [{"id": d.pk, "paypal_dispute_id": d.paypal_dispute_id, "status": d.status, "reason": d.reason}
                for d in obj.disputes.all()]

    def get_assessment(self, obj):
        a = self._latest(obj)
        return AssessmentSerializer(a).data if a else None


class DisputeSerializer(serializers.ModelSerializer):
    paypal_order_id = serializers.CharField(source="order.paypal_order_id", default="")
    buyer = serializers.SerializerMethodField()
    copilot = serializers.SerializerMethodField()

    class Meta:
        model = Dispute
        fields = [
            "id", "paypal_dispute_id", "paypal_order_id", "buyer", "reason", "status", "amount", "currency",
            "seller_response_due_at", "outcome", "created_at", "copilot",
        ]

    def get_buyer(self, obj):
        return str(obj.order.buyer) if obj.order else ""

    def get_copilot(self, obj):
        case = getattr(obj, "case", None)
        if case is None:
            return None
        return {"status": case.status, "recommendation": case.recommendation, "confidence": case.confidence}
