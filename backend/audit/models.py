from django.db import models


class AuditEvent(models.Model):
    """Append-only record of every score, AI output, human decision and PayPal call."""

    ACTOR_CHOICES = [("system", "System"), ("ai", "AI"), ("seller", "Seller"), ("paypal", "PayPal")]

    actor = models.CharField(max_length=10, choices=ACTOR_CHOICES)
    action = models.CharField(max_length=60)  # e.g. order.scored, webhook.received
    object_type = models.CharField(max_length=40, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    paypal_id = models.CharField(max_length=64, blank=True)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]


def record(actor: str, action: str, *, obj=None, paypal_id: str = "", **payload) -> AuditEvent:
    return AuditEvent.objects.create(
        actor=actor,
        action=action,
        object_type=type(obj).__name__ if obj is not None else "",
        object_id=str(obj.pk) if obj is not None else "",
        paypal_id=paypal_id,
        payload=payload,
    )
