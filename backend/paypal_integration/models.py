from django.db import models


class MockPayPalObject(models.Model):
    """
    Storage for the mock PayPal client: stands in for PayPal's own database.

    The demo simulator writes PayPal-shaped JSON here, then fires a webhook.
    The webhook handler fetches the object back through the client exactly as
    it would from the real API. Unused when PAYPAL_MODE=sandbox.
    """

    kind = models.CharField(max_length=20)  # order / dispute
    paypal_id = models.CharField(max_length=64)
    data = models.JSONField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("kind", "paypal_id")]
