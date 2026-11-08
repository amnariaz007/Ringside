"""
Commerce data mirrored from PayPal.

Buyer emails and phones are stored only as salted hashes (plus the email
domain, which the disposable-email rule needs). Raw PayPal JSON is kept on
orders and disputes so nothing is lost if we parse a field wrongly.
"""

from django.db import models


class Seller(models.Model):
    name = models.CharField(max_length=200)
    paypal_merchant_id = models.CharField(max_length=64, unique=True)
    currency = models.CharField(max_length=3, default="USD")
    timezone = models.CharField(max_length=40, default="UTC")  # IANA name, e.g. America/Chicago
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Buyer(models.Model):
    """A PayPal payer. Global (not per seller) so cross-shop signals are possible later."""

    payer_id = models.CharField(max_length=64, unique=True)
    email_hash = models.CharField(max_length=64, db_index=True)
    # Hash of the email with digits and dots stripped from the local part, so
    # ali.k1@x.com and alik2@x.com share a stem: a common fraud-ring pattern.
    email_stem_hash = models.CharField(max_length=64, db_index=True)
    email_domain = models.CharField(max_length=255)
    phone_hash = models.CharField(max_length=64, blank=True, db_index=True)
    display_name = models.CharField(max_length=200, blank=True)
    country_code = models.CharField(max_length=2, blank=True)
    account_status = models.CharField(max_length=20, blank=True)  # VERIFIED / UNVERIFIED
    first_seen_at = models.DateTimeField()

    def __str__(self):
        return self.display_name or self.payer_id


class Address(models.Model):
    """A normalised shipping address. Shared rows are how buyers get linked."""

    normalized_key = models.CharField(max_length=64, unique=True)  # hash of normalised fields
    line1 = models.CharField(max_length=300)
    line2 = models.CharField(max_length=300, blank=True)
    city = models.CharField(max_length=120, blank=True)
    state = models.CharField(max_length=120, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country_code = models.CharField(max_length=2)
    is_reshipper = models.BooleanField(default=False)

    class Meta:
        verbose_name_plural = "addresses"

    def __str__(self):
        return f"{self.line1}, {self.city} {self.country_code}"


class Order(models.Model):
    seller = models.ForeignKey(Seller, on_delete=models.CASCADE, related_name="orders")
    buyer = models.ForeignKey(Buyer, on_delete=models.PROTECT, related_name="orders")
    shipping_address = models.ForeignKey(
        Address, on_delete=models.PROTECT, null=True, blank=True, related_name="orders"
    )
    paypal_order_id = models.CharField(max_length=64, unique=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    payer_country = models.CharField(max_length=2, blank=True)
    status = models.CharField(max_length=30)
    created_at = models.DateTimeField(db_index=True)  # PayPal create_time, not row insert time
    raw = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.paypal_order_id


class Capture(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="captures")
    paypal_capture_id = models.CharField(max_length=64, unique=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=30)
    # ELIGIBLE / PARTIALLY_ELIGIBLE / NOT_ELIGIBLE, straight from PayPal.
    seller_protection_status = models.CharField(max_length=30, blank=True)
    seller_protection_categories = models.JSONField(default=list)
    captured_at = models.DateTimeField()

    def __str__(self):
        return self.paypal_capture_id


class Refund(models.Model):
    capture = models.ForeignKey(Capture, on_delete=models.CASCADE, related_name="refunds")
    paypal_refund_id = models.CharField(max_length=64, unique=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=30)
    created_at = models.DateTimeField()


class Dispute(models.Model):
    paypal_dispute_id = models.CharField(max_length=64, unique=True)
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True, related_name="disputes")
    capture = models.ForeignKey(Capture, on_delete=models.SET_NULL, null=True, blank=True, related_name="disputes")
    reason = models.CharField(max_length=60)  # e.g. MERCHANDISE_OR_SERVICE_NOT_RECEIVED
    status = models.CharField(max_length=60)  # e.g. WAITING_FOR_SELLER_RESPONSE, RESOLVED
    dispute_state = models.CharField(max_length=60, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    seller_response_due_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(max_length=60, blank=True)  # RESOLVED_BUYER_FAVOUR / RESOLVED_SELLER_FAVOUR
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    raw = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.paypal_dispute_id


class Shipment(models.Model):
    """
    How the seller shipped an order. This is the core evidence for "item not
    received" disputes (PayPal's PROOF_OF_FULFILLMENT takes carrier and tracking).
    The demo seeds it; in production it comes from the seller's shop or
    PayPal's Add Tracking API.
    """

    STATUS_CHOICES = [("SHIPPED", "Shipped"), ("IN_TRANSIT", "In transit"), ("DELIVERED", "Delivered")]

    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="shipment")
    carrier = models.CharField(max_length=40)  # PayPal carrier code, e.g. USPS, UPS, FEDEX
    tracking_number = models.CharField(max_length=64)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    shipped_at = models.DateTimeField()
    delivered_at = models.DateTimeField(null=True, blank=True)
    # Shipped to the address on the PayPal transaction (required for Seller Protection).
    to_paypal_address = models.BooleanField(default=True)
    signature_confirmed = models.BooleanField(default=False)
