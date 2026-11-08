from django.db import models


class WebhookEvent(models.Model):
    """Every PayPal webhook, stored raw before processing. event_id makes processing idempotent."""

    event_id = models.CharField(max_length=64, unique=True)
    event_type = models.CharField(max_length=80)
    resource_id = models.CharField(max_length=64, blank=True)
    raw = models.JSONField()
    verified = models.BooleanField(default=False)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-received_at"]
